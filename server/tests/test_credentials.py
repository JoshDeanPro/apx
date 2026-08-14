from __future__ import annotations

import pytest
from sqlalchemy import select

from openpower_api import db
from openpower_api.credentials import verify_credential


async def _make_agent(client, headers) -> str:
    resp = await client.post("/api/v1/agents", json={"name": "Buddy"}, headers=headers)
    return resp.json()["id"]


@pytest.mark.asyncio
async def test_credential_creation_returns_secret_once(client, auth_header):
    headers = auth_header()
    agent_id = await _make_agent(client, headers)

    resp = await client.post(f"/api/v1/agents/{agent_id}/credentials", json={}, headers=headers)
    assert resp.status_code == 201
    body = resp.json()
    assert "secret" in body and len(body["secret"]) > 20
    credential_id = body["credential_id"]

    # Subsequent GETs never include the secret.
    list_resp = await client.get(f"/api/v1/agents/{agent_id}/credentials", headers=headers)
    assert list_resp.status_code == 200
    for cred in list_resp.json():
        assert "secret" not in cred


@pytest.mark.asyncio
async def test_credential_rotation_invalidates_old(client, auth_header):
    headers = auth_header()
    agent_id = await _make_agent(client, headers)

    created = (await client.post(f"/api/v1/agents/{agent_id}/credentials", json={}, headers=headers)).json()
    old_credential_id = created["credential_id"]
    old_secret = created["secret"]

    rotate_resp = await client.post(
        f"/api/v1/agents/{agent_id}/credentials/rotate",
        json={"credential_id": old_credential_id},
        headers=headers,
    )
    assert rotate_resp.status_code == 201
    new_body = rotate_resp.json()
    assert new_body["credential_id"] != old_credential_id
    new_secret = new_body["secret"]
    assert new_secret != old_secret

    sessionmaker = db.get_sessionmaker()
    async with sessionmaker() as session:
        old_credential = await verify_credential(
            session, credential_id=old_credential_id, plaintext_secret=old_secret
        )
        assert old_credential is None  # rotated-out credential rejected

        new_credential = await verify_credential(
            session, credential_id=new_body["credential_id"], plaintext_secret=new_secret
        )
        assert new_credential is not None


@pytest.mark.asyncio
async def test_revoked_credential_rejected_on_verification(client, auth_header):
    headers = auth_header()
    agent_id = await _make_agent(client, headers)

    created = (await client.post(f"/api/v1/agents/{agent_id}/credentials", json={}, headers=headers)).json()
    credential_id = created["credential_id"]
    secret = created["secret"]

    revoke_resp = await client.post(
        f"/api/v1/agents/{agent_id}/credentials/revoke",
        json={"credential_id": credential_id},
        headers=headers,
    )
    assert revoke_resp.status_code == 200
    assert revoke_resp.json()["revoked_at"] is not None

    sessionmaker = db.get_sessionmaker()
    async with sessionmaker() as session:
        result = await verify_credential(session, credential_id=credential_id, plaintext_secret=secret)
        assert result is None


@pytest.mark.asyncio
async def test_credential_scoped_to_owner(client, auth_header):
    owner_headers = auth_header()
    other_headers = auth_header()
    agent_id = await _make_agent(client, owner_headers)

    resp = await client.post(f"/api/v1/agents/{agent_id}/credentials", json={}, headers=other_headers)
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_audit_events_never_contain_credential_value(client, auth_header):
    headers = auth_header()
    agent_id = await _make_agent(client, headers)

    created = (await client.post(f"/api/v1/agents/{agent_id}/credentials", json={}, headers=headers)).json()
    secret = created["secret"]

    sessionmaker = db.get_sessionmaker()
    async with sessionmaker() as session:
        result = await session.execute(select(db.AuditEvent))
        events = result.scalars().all()

    assert any(e.event_type == "agent.credential.created" for e in events)
    for event in events:
        serialized = str(event.audit_metadata)
        assert secret not in serialized
        assert "secret_hash" not in event.audit_metadata
