from __future__ import annotations

import base64
import hashlib
import hmac
import json

import pytest
from sqlalchemy import select

from openpower_api import db
from openpower_api.config import get_settings


def _verify_hs256(token: str, secret: str) -> dict:
    header_b64, payload_b64, sig_b64 = token.split(".")

    def pad(s: str) -> bytes:
        return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))

    expected = hmac.new(secret.encode(), f"{header_b64}.{payload_b64}".encode(), hashlib.sha256).digest()
    assert hmac.compare_digest(expected, pad(sig_b64))
    return json.loads(pad(payload_b64))


async def _make_agent_with_identity(client, headers) -> tuple[str, str]:
    agent_resp = await client.post("/api/v1/agents", json={"name": "AXP on Mac"}, headers=headers)
    agent_id = agent_resp.json()["id"]
    identity_resp = await client.post(f"/api/v1/agents/{agent_id}/identity", json={}, headers=headers)
    identity_key = identity_resp.json()["identity_key"]
    return agent_id, identity_key


@pytest.mark.asyncio
async def test_token_requires_identity_first(client, auth_header):
    headers = auth_header()
    agent_resp = await client.post("/api/v1/agents", json={"name": "No identity yet"}, headers=headers)
    agent_id = agent_resp.json()["id"]

    resp = await client.post(f"/api/v1/agents/{agent_id}/openpower-token", headers=headers)
    assert resp.status_code == 409


@pytest.mark.asyncio
async def test_token_503_when_shared_secret_unconfigured(client, auth_header, monkeypatch):
    monkeypatch.delenv("OPENPOWER_AXP_SHARED_SECRET", raising=False)
    get_settings.cache_clear()
    headers = auth_header()
    agent_id, _ = await _make_agent_with_identity(client, headers)

    resp = await client.post(f"/api/v1/agents/{agent_id}/openpower-token", headers=headers)
    assert resp.status_code == 503


@pytest.mark.asyncio
async def test_token_is_valid_hs256_and_verifiable_by_axp(client, auth_header, monkeypatch):
    monkeypatch.setenv("OPENPOWER_AXP_SHARED_SECRET", "test-shared-secret")
    get_settings.cache_clear()
    headers = auth_header()
    agent_id, identity_key = await _make_agent_with_identity(client, headers)

    resp = await client.post(f"/api/v1/agents/{agent_id}/openpower-token", headers=headers)
    assert resp.status_code == 200
    body = resp.json()
    assert body["identity_key"] == identity_key

    claims = _verify_hs256(body["token"], "test-shared-secret")
    assert claims["sub"] == identity_key
    assert claims["iss"] == "openpower.one"
    assert claims["aud"] == "axp"
    assert claims["principal_type"] == "agent"

    # Wrong secret must fail verification -- this is the whole point of HS256.
    with pytest.raises(AssertionError):
        _verify_hs256(body["token"], "wrong-secret")


@pytest.mark.asyncio
async def test_token_scoped_to_owner(client, auth_header, monkeypatch):
    monkeypatch.setenv("OPENPOWER_AXP_SHARED_SECRET", "test-shared-secret")
    get_settings.cache_clear()
    owner_headers = auth_header()
    other_headers = auth_header()
    agent_id, _ = await _make_agent_with_identity(client, owner_headers)

    resp = await client.post(f"/api/v1/agents/{agent_id}/openpower-token", headers=other_headers)
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_status_endpoint_unauthenticated_and_reflects_revocation(client, auth_header):
    headers = auth_header()
    _, identity_key = await _make_agent_with_identity(client, headers)

    # No Authorization header at all -- this mirrors AXP's own plain GET.
    resp = await client.get(f"/api/v1/agents/{identity_key}/status")
    assert resp.status_code == 200
    assert resp.json() == {"revoked": False}

    resp = await client.get("/api/v1/agents/agent:nonexistent:nowhere/status")
    assert resp.status_code == 200
    assert resp.json() == {"revoked": True}


@pytest.mark.asyncio
async def test_status_reflects_disabled_identity(client, auth_header):
    headers = auth_header()
    _, identity_key = await _make_agent_with_identity(client, headers)

    sessionmaker = db.get_sessionmaker()
    async with sessionmaker() as session:
        result = await session.execute(
            select(db.AgentIdentity).where(db.AgentIdentity.identity_key == identity_key)
        )
        identity = result.scalar_one()
        identity.status = "revoked"
        await session.commit()

    resp = await client.get(f"/api/v1/agents/{identity_key}/status")
    assert resp.status_code == 200
    assert resp.json() == {"revoked": True}


@pytest.mark.asyncio
async def test_audit_event_never_contains_token(client, auth_header, monkeypatch):
    monkeypatch.setenv("OPENPOWER_AXP_SHARED_SECRET", "test-shared-secret")
    get_settings.cache_clear()
    headers = auth_header()
    agent_id, _ = await _make_agent_with_identity(client, headers)

    resp = await client.post(f"/api/v1/agents/{agent_id}/openpower-token", headers=headers)
    token = resp.json()["token"]

    sessionmaker = db.get_sessionmaker()
    async with sessionmaker() as session:
        result = await session.execute(select(db.AuditEvent))
        events = result.scalars().all()

    assert any(e.event_type == "agent.openpower_token.issued" for e in events)
    for event in events:
        assert token not in str(event.audit_metadata)
