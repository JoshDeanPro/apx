"""Device linking: AXP <-> openpower.one, OAuth-device-authorization-grant
shaped (RFC 8628 in spirit, not a literal implementation). Exists so a CLI/
agent on any machine can link to a human's account without ever needing a
localhost callback, a copy-pasted secret, or the website having any way to
"just know" what happened on that machine -- approval only ever happens
through the website's own already-authenticated session.

Flow:
  1. POST /device/link            (no auth)   AXP asks for a code.
  2. AXP shows the human `user_code` + `verification_uri`; human opens it
     in their own browser, already signed in (or signs in now).
  3. GET  /device/link/{user_code} (human auth) website shows what it's for.
  4. POST /device/link/approve     (human auth) website approves it.
  5. POST /device/token            (no auth)   AXP polls with `device_code`
     until it observes "approved", then receives the HS256 identity token
     exactly once (device_code is single-use from that point on).
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..audit import record_audit_event
from ..auth import AuthenticatedUser, get_current_user
from ..config import get_settings
from ..credentials import generate_device_code, generate_user_code
from ..db import AgentIdentity, AgentProfile, DeviceLinkRequest, get_session
from ..openpower_axp import mint_jwt_hs256
from ..ratelimit import rate_limited_by_ip
from ..schemas import (
    DeviceLinkApprovedOut,
    DeviceLinkCreate,
    DeviceLinkCreatedOut,
    DeviceLinkDecision,
    DeviceLinkLookupOut,
    DeviceTokenIn,
    DeviceTokenOut,
)

router = APIRouter(prefix="/device", tags=["device"])

_CODE_TTL = timedelta(minutes=10)
_POLL_INTERVAL_SECONDS = 5


def _actor_for(user: AuthenticatedUser) -> str:
    return f"user:{user.id}"


def _aware(dt: datetime) -> datetime:
    return dt if dt.tzinfo is not None else dt.replace(tzinfo=timezone.utc)


@router.post("/link", response_model=DeviceLinkCreatedOut, status_code=status.HTTP_201_CREATED)
async def create_device_link(
    body: DeviceLinkCreate,
    session: AsyncSession = Depends(get_session),
    _: None = Depends(rate_limited_by_ip("device_link_create", max_requests=20, window_seconds=600)),
) -> DeviceLinkCreatedOut:
    now = datetime.now(timezone.utc)
    link = DeviceLinkRequest(
        device_code=generate_device_code(),
        user_code=generate_user_code(),
        agent_name=body.agent_name,
        status="pending",
        expires_at=now + _CODE_TTL,
    )
    session.add(link)
    await session.commit()

    return DeviceLinkCreatedOut(
        device_code=link.device_code,
        user_code=link.user_code,
        verification_uri="https://openpower.dev/app/link",
        expires_in=int(_CODE_TTL.total_seconds()),
        interval=_POLL_INTERVAL_SECONDS,
    )


@router.get("/link/{user_code}", response_model=DeviceLinkLookupOut)
async def lookup_device_link(
    user_code: str,
    user: AuthenticatedUser = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> DeviceLinkLookupOut:
    """Authenticated so the website can show "Link device 'AXP on workstation'?"
    before the human commits to approving or denying it."""
    result = await session.execute(select(DeviceLinkRequest).where(DeviceLinkRequest.user_code == user_code))
    link = result.scalar_one_or_none()
    if link is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Code not found")
    effective_status = link.status
    if effective_status == "pending" and _aware(link.expires_at) < datetime.now(timezone.utc):
        effective_status = "expired"
    return DeviceLinkLookupOut(agent_name=link.agent_name, status=effective_status, expires_at=link.expires_at)


async def _resolve_pending(session: AsyncSession, user_code: str) -> DeviceLinkRequest:
    result = await session.execute(select(DeviceLinkRequest).where(DeviceLinkRequest.user_code == user_code))
    link = result.scalar_one_or_none()
    if link is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Code not found")
    if link.status != "pending":
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=f"Code is already {link.status}")
    if _aware(link.expires_at) < datetime.now(timezone.utc):
        link.status = "expired"
        await session.commit()
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Code has expired")
    return link


@router.post("/link/approve", response_model=DeviceLinkApprovedOut)
async def approve_device_link(
    body: DeviceLinkDecision,
    user: AuthenticatedUser = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> DeviceLinkApprovedOut:
    link = await _resolve_pending(session, body.user_code)

    agent = AgentProfile(owner_id=user.id, name=link.agent_name, provider="axp", status="active")
    session.add(agent)
    await session.flush()

    identity_key = f"agent:axp:{agent.id.hex[:12]}"
    identity = AgentIdentity(agent_id=agent.id, owner_id=user.id, identity_key=identity_key, status="active")
    session.add(identity)
    await session.flush()

    link.status = "approved"
    link.owner_id = user.id
    link.agent_id = agent.id
    link.identity_key = identity_key
    link.resolved_at = datetime.now(timezone.utc)

    await record_audit_event(
        session,
        owner_id=user.id,
        actor=_actor_for(user),
        event_type="device_link.approved",
        target=identity_key,
        metadata={"agent_id": str(agent.id), "agent_name": link.agent_name},
    )
    await session.commit()

    return DeviceLinkApprovedOut(agent_id=agent.id, identity_key=identity_key)


@router.post("/link/deny", status_code=status.HTTP_204_NO_CONTENT)
async def deny_device_link(
    body: DeviceLinkDecision,
    user: AuthenticatedUser = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> None:
    link = await _resolve_pending(session, body.user_code)
    link.status = "denied"
    link.resolved_at = datetime.now(timezone.utc)

    await record_audit_event(
        session,
        owner_id=user.id,
        actor=_actor_for(user),
        event_type="device_link.denied",
        target=link.user_code,
        metadata={"agent_name": link.agent_name},
    )
    await session.commit()


@router.post("/token/personal", response_model=DeviceTokenOut)
async def issue_personal_token(
    body: DeviceLinkCreate,
    user: AuthenticatedUser = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
    _: None = Depends(rate_limited_by_ip("device_token_personal", max_requests=20, window_seconds=600)),
) -> DeviceTokenOut:
    """The no-browser-round-trip path: already-authenticated here (in the
    browser), so there's no code to relay back to a terminal and nothing to
    poll for -- mint the identity + token in the same request. Same identity
    shape as an approved device link (one AgentProfile/AgentIdentity per
    call, so 'op link --token ...' on N machines still gets N distinct
    identities, not one shared one) -- just without the two-machine dance
    that only exists to prove the human is the one clicking approve."""
    agent = AgentProfile(owner_id=user.id, name=body.agent_name, provider="axp", status="active")
    session.add(agent)
    await session.flush()

    identity_key = f"agent:axp:{agent.id.hex[:12]}"
    identity = AgentIdentity(agent_id=agent.id, owner_id=user.id, identity_key=identity_key, status="active")
    session.add(identity)
    await session.flush()

    await record_audit_event(
        session,
        owner_id=user.id,
        actor=_actor_for(user),
        event_type="device_link.personal_token_issued",
        target=identity_key,
        metadata={"agent_id": str(agent.id), "agent_name": body.agent_name},
    )

    settings = get_settings()
    if not settings.openpower_axp_shared_secret:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="AXP token issuance is not configured on this server",
        )
    token, exp = mint_jwt_hs256(
        subject=identity_key,
        principal_type="agent",
        secret=settings.openpower_axp_shared_secret,
        ttl_seconds=settings.openpower_axp_token_ttl_days * 86400,
    )
    await session.commit()

    return DeviceTokenOut(identity_key=identity_key, token=token, expires_at=datetime.fromtimestamp(exp, tz=timezone.utc))


@router.post("/token")
async def poll_device_token(
    body: DeviceTokenIn,
    session: AsyncSession = Depends(get_session),
    _: None = Depends(rate_limited_by_ip("device_token_poll", max_requests=120, window_seconds=600)),
):
    """No auth: device_code is the credential. Returns 200 with the token only
    once, on the poll that first observes 'approved' -- the row is then
    marked 'consumed' so a leaked/replayed device_code can't fetch it again.
    Every other outcome is a 400 with an OAuth-device-flow-style error code
    (authorization_pending / slow_down / expired_token / access_denied) so a
    polling client can distinguish "keep waiting" from "give up"."""
    result = await session.execute(select(DeviceLinkRequest).where(DeviceLinkRequest.device_code == body.device_code))
    link = result.scalar_one_or_none()
    if link is None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail={"error": "expired_token"})

    now = datetime.now(timezone.utc)
    if link.status == "pending" and _aware(link.expires_at) < now:
        link.status = "expired"
        await session.commit()

    if link.status == "expired":
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail={"error": "expired_token"})
    if link.status == "denied":
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail={"error": "access_denied"})
    if link.status == "consumed":
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail={"error": "expired_token"})
    if link.status == "pending":
        if link.last_polled_at is not None and (now - _aware(link.last_polled_at)).total_seconds() < _POLL_INTERVAL_SECONDS:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail={"error": "slow_down"})
        link.last_polled_at = now
        await session.commit()
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail={"error": "authorization_pending"})

    # status == "approved"
    settings = get_settings()
    if not settings.openpower_axp_shared_secret:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="AXP token issuance is not configured on this server",
        )
    token, exp = mint_jwt_hs256(
        subject=link.identity_key,
        principal_type="agent",
        secret=settings.openpower_axp_shared_secret,
        ttl_seconds=settings.openpower_axp_token_ttl_days * 86400,
    )
    link.status = "consumed"
    await session.commit()

    return {
        "identity_key": link.identity_key,
        "token": token,
        "expires_at": datetime.fromtimestamp(exp, tz=timezone.utc).isoformat(),
    }
