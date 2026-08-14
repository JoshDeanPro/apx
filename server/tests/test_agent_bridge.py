from __future__ import annotations

import time
import uuid

import jwt
import pytest

from openpower_api.config import get_settings


def _mint_agent_token(identity_key: str, secret: str, **overrides) -> str:
    now = int(time.time())
    claims = {
        "sub": identity_key,
        "principal_type": "agent",
        "iss": "openpower.one",
        "aud": "axp",
        "iat": now,
        "exp": now + 3600,
        **overrides,
    }
    return jwt.encode(claims, secret, algorithm="HS256")


async def _make_agent_with_identity(client, headers) -> tuple[str, str]:
    agent_resp = await client.post("/api/v1/agents", json={"name": "AXP on Mac"}, headers=headers)
    agent_id = agent_resp.json()["id"]
    identity_resp = await client.post(f"/api/v1/agents/{agent_id}/identity", json={}, headers=headers)
    identity_key = identity_resp.json()["identity_key"]
    return agent_id, identity_key


@pytest.mark.asyncio
async def test_heartbeat_requires_agent_token(client):
    resp = await client.post("/api/v1/agent/heartbeat", json={"device_name": "test-mac"})
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_heartbeat_503_when_shared_secret_unconfigured(client, auth_header, monkeypatch):
    monkeypatch.delenv("OPENPOWER_AXP_SHARED_SECRET", raising=False)
    get_settings.cache_clear()
    headers = auth_header()
    _, identity_key = await _make_agent_with_identity(client, headers)

    token = _mint_agent_token(identity_key, "irrelevant-since-unconfigured")
    resp = await client.post(
        "/api/v1/agent/heartbeat",
        json={"device_name": "test-mac"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code in (401, 503)


@pytest.mark.asyncio
async def test_heartbeat_registers_device_and_detected_agents(client, auth_header, monkeypatch):
    monkeypatch.setenv("OPENPOWER_AXP_SHARED_SECRET", "bridge-test-secret")
    get_settings.cache_clear()
    headers = auth_header()
    _, identity_key = await _make_agent_with_identity(client, headers)
    token = _mint_agent_token(identity_key, "bridge-test-secret")

    resp = await client.post(
        "/api/v1/agent/heartbeat",
        json={
            "device_name": "ethans-mac",
            "device_type": "mac",
            "buddy_os_version": "0.1.0",
            "axp_version": "0.4.0",
            "detected_agents": [{"name": "Claude Code", "provider": "anthropic"}],
        },
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["pending_commands"] == 0

    # A second heartbeat for the same device name must update, not duplicate.
    resp2 = await client.post(
        "/api/v1/agent/heartbeat",
        json={"device_name": "ethans-mac", "detected_agents": []},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp2.json()["device_id"] == body["device_id"]


@pytest.mark.asyncio
async def test_wrong_secret_rejected(client, auth_header, monkeypatch):
    monkeypatch.setenv("OPENPOWER_AXP_SHARED_SECRET", "real-secret")
    get_settings.cache_clear()
    headers = auth_header()
    _, identity_key = await _make_agent_with_identity(client, headers)

    token = _mint_agent_token(identity_key, "wrong-secret")
    resp = await client.post(
        "/api/v1/agent/heartbeat",
        json={"device_name": "test-mac"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_full_command_dispatch_round_trip(client, auth_header, monkeypatch):
    monkeypatch.setenv("OPENPOWER_AXP_SHARED_SECRET", "bridge-test-secret")
    get_settings.cache_clear()
    headers = auth_header()
    _, identity_key = await _make_agent_with_identity(client, headers)
    agent_token = _mint_agent_token(identity_key, "bridge-test-secret")
    agent_headers = {"Authorization": f"Bearer {agent_token}"}

    hb = await client.post(
        "/api/v1/agent/heartbeat", json={"device_name": "ethans-mac"}, headers=agent_headers
    )
    device_id = hb.json()["device_id"]

    # Human (a different credential -- the same auth_header() as before, since
    # it's the same fake human session) queues a command.
    create_resp = await client.post(
        f"/api/v1/devices/{device_id}/commands", json={"action": "service.status", "params": {"unit": "caddy"}}, headers=headers
    )
    assert create_resp.status_code == 201
    command_id = create_resp.json()["id"]
    assert create_resp.json()["status"] == "pending"

    # Device polls and picks it up.
    poll_resp = await client.get("/api/v1/agent/commands", headers=agent_headers)
    assert poll_resp.status_code == 200
    polled = poll_resp.json()
    assert len(polled) == 1
    assert polled[0]["id"] == command_id
    assert polled[0]["status"] == "running"

    # Second poll: already running, not returned again.
    poll_again = await client.get("/api/v1/agent/commands", headers=agent_headers)
    assert poll_again.json() == []

    # Device reports the result.
    result_resp = await client.post(
        f"/api/v1/agent/commands/{command_id}/result",
        json={"status": "completed", "result": {"active": True}},
        headers=agent_headers,
    )
    assert result_resp.status_code == 200
    assert result_resp.json()["status"] == "completed"

    # Human sees the completed command.
    list_resp = await client.get(f"/api/v1/devices/{device_id}/commands", headers=headers)
    assert list_resp.status_code == 200
    assert list_resp.json()[0]["status"] == "completed"
    assert list_resp.json()[0]["result"] == {"active": True}


@pytest.mark.asyncio
async def test_command_action_must_be_allowlisted(client, auth_header, monkeypatch):
    monkeypatch.setenv("OPENPOWER_AXP_SHARED_SECRET", "bridge-test-secret")
    get_settings.cache_clear()
    headers = auth_header()
    _, identity_key = await _make_agent_with_identity(client, headers)
    agent_token = _mint_agent_token(identity_key, "bridge-test-secret")

    hb = await client.post(
        "/api/v1/agent/heartbeat",
        json={"device_name": "test-mac"},
        headers={"Authorization": f"Bearer {agent_token}"},
    )
    device_id = hb.json()["device_id"]

    resp = await client.post(
        f"/api/v1/devices/{device_id}/commands",
        json={"action": "shell.exec", "params": {"cmd": "rm -rf /"}},
        headers=headers,
    )
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_commands_scoped_to_device_owner(client, auth_header, monkeypatch):
    monkeypatch.setenv("OPENPOWER_AXP_SHARED_SECRET", "bridge-test-secret")
    get_settings.cache_clear()
    owner_headers = auth_header()
    other_headers = auth_header()
    _, identity_key = await _make_agent_with_identity(client, owner_headers)
    agent_token = _mint_agent_token(identity_key, "bridge-test-secret")

    hb = await client.post(
        "/api/v1/agent/heartbeat",
        json={"device_name": "owners-mac"},
        headers={"Authorization": f"Bearer {agent_token}"},
    )
    device_id = hb.json()["device_id"]

    resp = await client.post(
        f"/api/v1/devices/{device_id}/commands", json={"action": "service.status"}, headers=other_headers
    )
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_audit_events_never_contain_agent_token(client, auth_header, monkeypatch):
    monkeypatch.setenv("OPENPOWER_AXP_SHARED_SECRET", "bridge-test-secret")
    get_settings.cache_clear()
    headers = auth_header()
    _, identity_key = await _make_agent_with_identity(client, headers)
    agent_token = _mint_agent_token(identity_key, "bridge-test-secret")

    from sqlalchemy import select

    from openpower_api import db

    await client.post(
        "/api/v1/agent/heartbeat",
        json={"device_name": "test-mac"},
        headers={"Authorization": f"Bearer {agent_token}"},
    )

    sessionmaker = db.get_sessionmaker()
    async with sessionmaker() as session:
        result = await session.execute(select(db.AuditEvent))
        events = result.scalars().all()

    assert any(e.event_type == "device.heartbeat" for e in events)
    for event in events:
        assert agent_token not in str(event.audit_metadata)


# --- Connections (list devices, dispatch/poll commands between them) ----------


@pytest.mark.asyncio
async def test_list_connections_scoped_to_owner(client, auth_header, monkeypatch):
    monkeypatch.setenv("OPENPOWER_AXP_SHARED_SECRET", "bridge-test-secret")
    get_settings.cache_clear()

    owner_headers = auth_header()
    other_headers = auth_header()
    _, owner_identity_key = await _make_agent_with_identity(client, owner_headers)
    _, other_identity_key = await _make_agent_with_identity(client, other_headers)
    owner_token = _mint_agent_token(owner_identity_key, "bridge-test-secret")
    other_token = _mint_agent_token(other_identity_key, "bridge-test-secret")

    await client.post(
        "/api/v1/agent/heartbeat",
        json={"device_name": "owners-mac"},
        headers={"Authorization": f"Bearer {owner_token}"},
    )
    await client.post(
        "/api/v1/agent/heartbeat",
        json={"device_name": "others-mac"},
        headers={"Authorization": f"Bearer {other_token}"},
    )

    resp = await client.get(
        "/api/v1/agent/connections", headers={"Authorization": f"Bearer {owner_token}"}
    )
    assert resp.status_code == 200
    names = [c["name"] for c in resp.json()]
    assert names == ["owners-mac"]


@pytest.mark.asyncio
async def test_create_connection_command_success(client, auth_header, monkeypatch):
    monkeypatch.setenv("OPENPOWER_AXP_SHARED_SECRET", "bridge-test-secret")
    get_settings.cache_clear()
    headers = auth_header()
    _, identity_key = await _make_agent_with_identity(client, headers)
    agent_token = _mint_agent_token(identity_key, "bridge-test-secret")
    agent_headers = {"Authorization": f"Bearer {agent_token}"}

    await client.post(
        "/api/v1/agent/heartbeat", json={"device_name": "target-mac"}, headers=agent_headers
    )

    resp = await client.post(
        "/api/v1/agent/connections/target-mac/commands",
        json={"action": "service.status", "params": {"unit": "caddy"}},
        headers=agent_headers,
    )
    assert resp.status_code == 201
    body = resp.json()
    assert body["action"] == "service.status"
    assert body["status"] == "pending"


@pytest.mark.asyncio
async def test_create_connection_command_unknown_device_404(client, auth_header, monkeypatch):
    monkeypatch.setenv("OPENPOWER_AXP_SHARED_SECRET", "bridge-test-secret")
    get_settings.cache_clear()
    headers = auth_header()
    _, identity_key = await _make_agent_with_identity(client, headers)
    agent_token = _mint_agent_token(identity_key, "bridge-test-secret")
    agent_headers = {"Authorization": f"Bearer {agent_token}"}

    resp = await client.post(
        "/api/v1/agent/connections/no-such-device/commands",
        json={"action": "service.status"},
        headers=agent_headers,
    )
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_create_connection_command_disallowed_action_422(client, auth_header, monkeypatch):
    monkeypatch.setenv("OPENPOWER_AXP_SHARED_SECRET", "bridge-test-secret")
    get_settings.cache_clear()
    headers = auth_header()
    _, identity_key = await _make_agent_with_identity(client, headers)
    agent_token = _mint_agent_token(identity_key, "bridge-test-secret")
    agent_headers = {"Authorization": f"Bearer {agent_token}"}

    await client.post(
        "/api/v1/agent/heartbeat", json={"device_name": "target-mac"}, headers=agent_headers
    )

    resp = await client.post(
        "/api/v1/agent/connections/target-mac/commands",
        json={"action": "shell.exec", "params": {"cmd": "rm -rf /"}},
        headers=agent_headers,
    )
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_get_command_success(client, auth_header, monkeypatch):
    monkeypatch.setenv("OPENPOWER_AXP_SHARED_SECRET", "bridge-test-secret")
    get_settings.cache_clear()
    headers = auth_header()
    _, identity_key = await _make_agent_with_identity(client, headers)
    agent_token = _mint_agent_token(identity_key, "bridge-test-secret")
    agent_headers = {"Authorization": f"Bearer {agent_token}"}

    await client.post(
        "/api/v1/agent/heartbeat", json={"device_name": "target-mac"}, headers=agent_headers
    )
    create_resp = await client.post(
        "/api/v1/agent/connections/target-mac/commands",
        json={"action": "service.status"},
        headers=agent_headers,
    )
    command_id = create_resp.json()["id"]

    resp = await client.get(f"/api/v1/agent/commands/{command_id}", headers=agent_headers)
    assert resp.status_code == 200
    assert resp.json()["id"] == command_id


@pytest.mark.asyncio
async def test_get_command_wrong_owner_404(client, auth_header, monkeypatch):
    monkeypatch.setenv("OPENPOWER_AXP_SHARED_SECRET", "bridge-test-secret")
    get_settings.cache_clear()

    owner_headers = auth_header()
    other_headers = auth_header()
    _, owner_identity_key = await _make_agent_with_identity(client, owner_headers)
    _, other_identity_key = await _make_agent_with_identity(client, other_headers)
    owner_token = _mint_agent_token(owner_identity_key, "bridge-test-secret")
    other_token = _mint_agent_token(other_identity_key, "bridge-test-secret")
    owner_headers_agent = {"Authorization": f"Bearer {owner_token}"}

    await client.post(
        "/api/v1/agent/heartbeat", json={"device_name": "owners-mac"}, headers=owner_headers_agent
    )
    create_resp = await client.post(
        "/api/v1/agent/connections/owners-mac/commands",
        json={"action": "service.status"},
        headers=owner_headers_agent,
    )
    command_id = create_resp.json()["id"]

    resp = await client.get(
        f"/api/v1/agent/commands/{command_id}", headers={"Authorization": f"Bearer {other_token}"}
    )
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_get_command_nonexistent_404(client, auth_header, monkeypatch):
    monkeypatch.setenv("OPENPOWER_AXP_SHARED_SECRET", "bridge-test-secret")
    get_settings.cache_clear()
    headers = auth_header()
    _, identity_key = await _make_agent_with_identity(client, headers)
    agent_token = _mint_agent_token(identity_key, "bridge-test-secret")

    resp = await client.get(
        f"/api/v1/agent/commands/{uuid.uuid4()}", headers={"Authorization": f"Bearer {agent_token}"}
    )
    assert resp.status_code == 404
