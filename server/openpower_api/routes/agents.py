from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..audit import record_audit_event
from ..auth import AuthenticatedUser, get_current_user
from ..config import get_settings
from ..credentials import generate_credential_id, generate_secret, hash_secret
from ..db import AgentCredential, AgentIdentity, AgentProfile, get_session
from ..openpower_axp import mint_jwt_hs256
from ..ratelimit import rate_limited
from ..schemas import (
    AgentCreate,
    AgentCredentialCreate,
    AgentCredentialCreatedOut,
    AgentCredentialOut,
    AgentCredentialRevokeIn,
    AgentCredentialRotateIn,
    AgentIdentityCreate,
    AgentIdentityOut,
    AgentOut,
    AgentUpdate,
    AXPStatusOut,
    AXPTokenOut,
)

router = APIRouter(prefix="/agents", tags=["agents"])


async def _get_owned_agent(session: AsyncSession, agent_id: uuid.UUID, owner_id: uuid.UUID) -> AgentProfile:
    """Fetch an agent and enforce ownership. 404 (never 403) on mismatch/missing
    so we don't leak whether another user's resource exists."""
    result = await session.execute(select(AgentProfile).where(AgentProfile.id == agent_id))
    agent = result.scalar_one_or_none()
    if agent is None or agent.owner_id != owner_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Agent not found")
    return agent


def actor_for(user: AuthenticatedUser) -> str:
    return f"user:{user.id}"


@router.get("", response_model=list[AgentOut])
async def list_agents(
    user: AuthenticatedUser = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> list[AgentProfile]:
    result = await session.execute(select(AgentProfile).where(AgentProfile.owner_id == user.id))
    return list(result.scalars().all())


@router.post("", response_model=AgentOut, status_code=status.HTTP_201_CREATED)
async def create_agent(
    body: AgentCreate,
    user: AuthenticatedUser = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> AgentProfile:
    agent = AgentProfile(
        owner_id=user.id,
        name=body.name,
        provider=body.provider,
        device_id=body.device_id,
        permissions=body.permissions,
    )
    session.add(agent)
    await session.flush()

    await record_audit_event(
        session,
        owner_id=user.id,
        actor=actor_for(user),
        event_type="agent.created",
        target=str(agent.id),
        metadata={"name": agent.name, "provider": agent.provider},
    )
    await session.commit()
    await session.refresh(agent)
    return agent


@router.get("/{agent_id}", response_model=AgentOut)
async def get_agent(
    agent_id: uuid.UUID,
    user: AuthenticatedUser = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> AgentProfile:
    return await _get_owned_agent(session, agent_id, user.id)


@router.patch("/{agent_id}", response_model=AgentOut)
async def update_agent(
    agent_id: uuid.UUID,
    body: AgentUpdate,
    user: AuthenticatedUser = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> AgentProfile:
    agent = await _get_owned_agent(session, agent_id, user.id)

    updates = body.model_dump(exclude_unset=True)
    became_disabled = updates.get("status") == "disabled" and agent.status != "disabled"

    for field, value in updates.items():
        setattr(agent, field, value)

    await session.flush()

    if became_disabled:
        await record_audit_event(
            session,
            owner_id=user.id,
            actor=actor_for(user),
            event_type="agent.disabled",
            target=str(agent.id),
        )

    await session.commit()
    await session.refresh(agent)
    return agent


# --- Identity ------------------------------------------------------------------


@router.post("/{agent_id}/identity", response_model=AgentIdentityOut, status_code=status.HTTP_201_CREATED)
async def create_or_assign_identity(
    agent_id: uuid.UUID,
    body: AgentIdentityCreate,
    user: AuthenticatedUser = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> AgentIdentity:
    agent = await _get_owned_agent(session, agent_id, user.id)

    existing = await session.execute(select(AgentIdentity).where(AgentIdentity.agent_id == agent.id))
    if existing.scalar_one_or_none() is not None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Agent already has an identity")

    assigning_existing_key = body.identity_key is not None

    if assigning_existing_key:
        identity_key = body.identity_key
        key_taken = await session.execute(
            select(AgentIdentity).where(AgentIdentity.identity_key == identity_key)
        )
        if key_taken.scalar_one_or_none() is not None:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Identity key already in use")
    else:
        provider = agent.provider or "agent"
        identity_key = f"agent:{provider}:{uuid.uuid4().hex[:12]}"

    identity = AgentIdentity(agent_id=agent.id, owner_id=user.id, identity_key=identity_key, status="active")
    session.add(identity)
    await session.flush()

    await record_audit_event(
        session,
        owner_id=user.id,
        actor=actor_for(user),
        event_type="agent.identity.assigned" if assigning_existing_key else "agent.identity.created",
        target=str(identity.id),
        metadata={"agent_id": str(agent.id), "identity_key": identity.identity_key},
    )
    await session.commit()
    await session.refresh(identity)
    return identity


# --- AXP identity linking --------------------------------------------------------
#
# Counterpart to AXP's own auth_openpower.py (LOCALCLOUD): a personal or agent
# AXP instance verifies a short-lived HS256 token against a shared secret, then
# checks revocation here. OpenPower only ever asserts identity -- AXP's local
# policy config alone decides what that identity may do on that machine.


@router.post("/{agent_id}/openpower-token", response_model=AXPTokenOut)
async def mint_openpower_token(
    agent_id: uuid.UUID,
    user: AuthenticatedUser = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> AXPTokenOut:
    agent = await _get_owned_agent(session, agent_id, user.id)

    result = await session.execute(select(AgentIdentity).where(AgentIdentity.agent_id == agent.id))
    identity = result.scalar_one_or_none()
    if identity is None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Agent has no OpenPower identity yet; create one first",
        )
    if identity.status != "active":
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Identity is not active")

    settings = get_settings()
    if not settings.openpower_axp_shared_secret:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="AXP token issuance is not configured on this server",
        )

    from datetime import datetime, timezone

    token, exp = mint_jwt_hs256(
        subject=identity.identity_key,
        principal_type="agent",
        secret=settings.openpower_axp_shared_secret,
        ttl_seconds=settings.openpower_axp_token_ttl_days * 86400,
    )

    await record_audit_event(
        session,
        owner_id=user.id,
        actor=actor_for(user),
        event_type="agent.openpower_token.issued",
        target=identity.identity_key,
        metadata={"agent_id": str(agent.id)},
    )
    await session.commit()

    return AXPTokenOut(
        identity_key=identity.identity_key,
        token=token,
        expires_at=datetime.fromtimestamp(exp, tz=timezone.utc),
    )


@router.get("/{identity_key}/status", response_model=AXPStatusOut)
async def openpower_identity_status(
    identity_key: str,
    session: AsyncSession = Depends(get_session),
) -> AXPStatusOut:
    """Unauthenticated by design -- this mirrors AXP's own plain GET (no bearer
    header sent) and answers only a low-sensitivity boolean. An unknown
    identity_key is reported revoked=True rather than 404, so a caller that
    already verified a token's signature never treats "not found" as "offline"."""
    result = await session.execute(
        select(AgentIdentity).where(AgentIdentity.identity_key == identity_key)
    )
    identity = result.scalar_one_or_none()
    if identity is None:
        return AXPStatusOut(revoked=True)
    return AXPStatusOut(revoked=identity.status != "active")


# --- Credentials -----------------------------------------------------------------


@router.post(
    "/{agent_id}/credentials",
    response_model=AgentCredentialCreatedOut,
    status_code=status.HTTP_201_CREATED,
)
async def create_credential(
    agent_id: uuid.UUID,
    body: AgentCredentialCreate,
    user: AuthenticatedUser = Depends(rate_limited("credential_create")),
    session: AsyncSession = Depends(get_session),
) -> AgentCredentialCreatedOut:
    agent = await _get_owned_agent(session, agent_id, user.id)

    plaintext = generate_secret()
    credential = AgentCredential(
        agent_id=agent.id,
        owner_id=user.id,
        credential_id=generate_credential_id(),
        secret_hash=hash_secret(plaintext),
        expires_at=body.expires_at,
    )
    session.add(credential)
    await session.flush()

    await record_audit_event(
        session,
        owner_id=user.id,
        actor=actor_for(user),
        event_type="agent.credential.created",
        target=credential.credential_id,
        metadata={"agent_id": str(agent.id)},
    )
    await session.commit()
    await session.refresh(credential)

    return AgentCredentialCreatedOut(
        id=credential.id,
        agent_id=credential.agent_id,
        credential_id=credential.credential_id,
        created_at=credential.created_at,
        last_used_at=credential.last_used_at,
        expires_at=credential.expires_at,
        rotated_at=credential.rotated_at,
        revoked_at=credential.revoked_at,
        secret=plaintext,
    )


@router.get("/{agent_id}/credentials", response_model=list[AgentCredentialOut])
async def list_credentials(
    agent_id: uuid.UUID,
    user: AuthenticatedUser = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> list[AgentCredential]:
    agent = await _get_owned_agent(session, agent_id, user.id)
    result = await session.execute(select(AgentCredential).where(AgentCredential.agent_id == agent.id))
    return list(result.scalars().all())


async def _find_credential_or_404(
    session: AsyncSession, agent: AgentProfile, credential_id: str | None
) -> AgentCredential:
    if credential_id is not None:
        result = await session.execute(
            select(AgentCredential).where(
                AgentCredential.agent_id == agent.id,
                AgentCredential.credential_id == credential_id,
            )
        )
    else:
        result = await session.execute(
            select(AgentCredential)
            .where(AgentCredential.agent_id == agent.id, AgentCredential.revoked_at.is_(None))
            .order_by(AgentCredential.created_at.desc())
        )
    credential = result.scalars().first() if credential_id is None else result.scalar_one_or_none()
    if credential is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Credential not found")
    return credential


@router.post(
    "/{agent_id}/credentials/rotate",
    response_model=AgentCredentialCreatedOut,
    status_code=status.HTTP_201_CREATED,
)
async def rotate_credential(
    agent_id: uuid.UUID,
    body: AgentCredentialRotateIn,
    user: AuthenticatedUser = Depends(rate_limited("credential_rotate")),
    session: AsyncSession = Depends(get_session),
) -> AgentCredentialCreatedOut:
    agent = await _get_owned_agent(session, agent_id, user.id)
    old_credential = await _find_credential_or_404(session, agent, body.credential_id)

    if old_credential.revoked_at is not None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Credential already revoked")

    from datetime import datetime, timezone

    now = datetime.now(timezone.utc)
    old_credential.revoked_at = now
    old_credential.rotated_at = now

    plaintext = generate_secret()
    new_credential = AgentCredential(
        agent_id=agent.id,
        owner_id=user.id,
        credential_id=generate_credential_id(),
        secret_hash=hash_secret(plaintext),
    )
    session.add(new_credential)
    await session.flush()

    await record_audit_event(
        session,
        owner_id=user.id,
        actor=actor_for(user),
        event_type="agent.credential.rotated",
        target=new_credential.credential_id,
        metadata={"agent_id": str(agent.id), "previous_credential_id": old_credential.credential_id},
    )
    await session.commit()
    await session.refresh(new_credential)

    return AgentCredentialCreatedOut(
        id=new_credential.id,
        agent_id=new_credential.agent_id,
        credential_id=new_credential.credential_id,
        created_at=new_credential.created_at,
        last_used_at=new_credential.last_used_at,
        expires_at=new_credential.expires_at,
        rotated_at=new_credential.rotated_at,
        revoked_at=new_credential.revoked_at,
        secret=plaintext,
    )


@router.post("/{agent_id}/credentials/revoke", response_model=AgentCredentialOut)
async def revoke_credential(
    agent_id: uuid.UUID,
    body: AgentCredentialRevokeIn,
    user: AuthenticatedUser = Depends(rate_limited("credential_revoke")),
    session: AsyncSession = Depends(get_session),
) -> AgentCredential:
    agent = await _get_owned_agent(session, agent_id, user.id)
    credential = await _find_credential_or_404(session, agent, body.credential_id)

    if credential.revoked_at is None:
        from datetime import datetime, timezone

        credential.revoked_at = datetime.now(timezone.utc)
        await session.flush()

        await record_audit_event(
            session,
            owner_id=user.id,
            actor=actor_for(user),
            event_type="agent.credential.revoked",
            target=credential.credential_id,
            metadata={"agent_id": str(agent.id)},
        )
        await session.commit()
        await session.refresh(credential)

    return credential
