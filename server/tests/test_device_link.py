from __future__ import annotations

import base64
import hashlib
import hmac
import json

import pytest

from openpower_api import db
from openpower_api.config import get_settings
from sqlalchemy import select


def _verify_hs256(token: str, secret: str) -> dict:
    header_b64, payload_b64, sig_b64 = token.split(".")

    def pad(s: str) -> bytes:
        return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))

    expected = hmac.new(secret.encode(), f"{header_b64}.{payload_b64}".encode(), hashlib.sha256).digest()
    assert hmac.compare_digest(expected, pad(sig_b64))
    return json.loads(pad(payload_b64))


@pytest.mark.asyncio
async def test_create_link_requires_no_auth(client):
    resp = await client.post("/api/v1/device/link", json={"agent_name": "AXP on test-mac"})
    assert resp.status_code == 201
    body = resp.json()
    assert body["user_code"].count("-") == 1
    assert len(body["device_code"]) > 20
    assert body["verification_uri"] == "https://openpower.dev/app/link"


@pytest.mark.asyncio
async def test_poll_before_approval_is_pending(client):
    created = (await client.post("/api/v1/device/link", json={"agent_name": "AXP"})).json()

    resp = await client.post("/api/v1/device/token", json={"device_code": created["device_code"]})
    assert resp.status_code == 400
    assert resp.json()["detail"]["error"] == "authorization_pending"


@pytest.mark.asyncio
async def test_poll_too_fast_is_slow_down(client):
    created = (await client.post("/api/v1/device/link", json={"agent_name": "AXP"})).json()

    first = await client.post("/api/v1/device/token", json={"device_code": created["device_code"]})
    assert first.json()["detail"]["error"] == "authorization_pending"
    second = await client.post("/api/v1/device/token", json={"device_code": created["device_code"]})
    assert second.status_code == 400
    assert second.json()["detail"]["error"] == "slow_down"


@pytest.mark.asyncio
async def test_unknown_device_code_is_expired_token(client):
    resp = await client.post("/api/v1/device/token", json={"device_code": "not-a-real-code"})
    assert resp.status_code == 400
    assert resp.json()["detail"]["error"] == "expired_token"


@pytest.mark.asyncio
async def test_lookup_requires_auth(client):
    created = (await client.post("/api/v1/device/link", json={"agent_name": "AXP"})).json()
    resp = await client.get(f"/api/v1/device/link/{created['user_code']}")
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_lookup_shows_agent_name_to_authenticated_human(client, auth_header):
    created = (await client.post("/api/v1/device/link", json={"agent_name": "AXP on ethan-mac"})).json()

    resp = await client.get(f"/api/v1/device/link/{created['user_code']}", headers=auth_header())
    assert resp.status_code == 200
    body = resp.json()
    assert body["agent_name"] == "AXP on ethan-mac"
    assert body["status"] == "pending"


@pytest.mark.asyncio
async def test_lookup_unknown_code_404(client, auth_header):
    resp = await client.get("/api/v1/device/link/ZZZZ-ZZZZ", headers=auth_header())
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_full_approve_flow_issues_working_token(client, auth_header, monkeypatch):
    monkeypatch.setenv("OPENPOWER_AXP_SHARED_SECRET", "device-flow-secret")
    get_settings.cache_clear()

    created = (await client.post("/api/v1/device/link", json={"agent_name": "AXP on ethan-mac"})).json()
    device_code, user_code = created["device_code"], created["user_code"]

    # AXP polls: still pending.
    pending = await client.post("/api/v1/device/token", json={"device_code": device_code})
    assert pending.json()["detail"]["error"] == "authorization_pending"

    # Human approves inside the website, in their own authenticated session.
    human_headers = auth_header()
    approve = await client.post("/api/v1/device/link/approve", json={"user_code": user_code}, headers=human_headers)
    assert approve.status_code == 200
    approved_body = approve.json()
    assert approved_body["identity_key"].startswith("agent:axp:")

    # AXP polls again (respecting the interval this time) and gets the token.
    sessionmaker = db.get_sessionmaker()
    async with sessionmaker() as session:
        result = await session.execute(select(db.DeviceLinkRequest).where(db.DeviceLinkRequest.device_code == device_code))
        link = result.scalar_one()
        link.last_polled_at = None
        await session.commit()

    token_resp = await client.post("/api/v1/device/token", json={"device_code": device_code})
    assert token_resp.status_code == 200
    token_body = token_resp.json()
    assert token_body["identity_key"] == approved_body["identity_key"]

    claims = _verify_hs256(token_body["token"], "device-flow-secret")
    assert claims["sub"] == approved_body["identity_key"]
    assert claims["aud"] == "axp"

    # device_code is single-use: polling again fails even immediately after.
    async with sessionmaker() as session:
        result = await session.execute(select(db.DeviceLinkRequest).where(db.DeviceLinkRequest.device_code == device_code))
        link = result.scalar_one()
        link.last_polled_at = None
        await session.commit()
    replay = await client.post("/api/v1/device/token", json={"device_code": device_code})
    assert replay.status_code == 400
    assert replay.json()["detail"]["error"] == "expired_token"


@pytest.mark.asyncio
async def test_deny_flow(client, auth_header):
    created = (await client.post("/api/v1/device/link", json={"agent_name": "AXP"})).json()

    deny_resp = await client.post(
        "/api/v1/device/link/deny", json={"user_code": created["user_code"]}, headers=auth_header()
    )
    assert deny_resp.status_code == 204

    poll = await client.post("/api/v1/device/token", json={"device_code": created["device_code"]})
    assert poll.status_code == 400
    assert poll.json()["detail"]["error"] == "access_denied"


@pytest.mark.asyncio
async def test_expired_code_rejected(client, auth_header):
    created = (await client.post("/api/v1/device/link", json={"agent_name": "AXP"})).json()

    sessionmaker = db.get_sessionmaker()
    async with sessionmaker() as session:
        from datetime import datetime, timedelta, timezone

        result = await session.execute(select(db.DeviceLinkRequest).where(db.DeviceLinkRequest.user_code == created["user_code"]))
        link = result.scalar_one()
        link.expires_at = datetime.now(timezone.utc) - timedelta(minutes=1)
        await session.commit()

    approve = await client.post(
        "/api/v1/device/link/approve", json={"user_code": created["user_code"]}, headers=auth_header()
    )
    assert approve.status_code == 409

    poll = await client.post("/api/v1/device/token", json={"device_code": created["device_code"]})
    assert poll.status_code == 400
    assert poll.json()["detail"]["error"] == "expired_token"


@pytest.mark.asyncio
async def test_audit_events_never_contain_token(client, auth_header, monkeypatch):
    monkeypatch.setenv("OPENPOWER_AXP_SHARED_SECRET", "device-flow-secret")
    get_settings.cache_clear()

    created = (await client.post("/api/v1/device/link", json={"agent_name": "AXP"})).json()
    await client.post("/api/v1/device/link/approve", json={"user_code": created["user_code"]}, headers=auth_header())
    token_resp = await client.post("/api/v1/device/token", json={"device_code": created["device_code"]})
    token = token_resp.json()["token"]

    sessionmaker = db.get_sessionmaker()
    async with sessionmaker() as session:
        result = await session.execute(select(db.AuditEvent))
        events = result.scalars().all()

    assert any(e.event_type == "device_link.approved" for e in events)
    for event in events:
        assert token not in str(event.audit_metadata)
