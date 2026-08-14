from __future__ import annotations

import uuid

import pytest


@pytest.mark.asyncio
async def test_create_and_get_agent(client, auth_header):
    headers = auth_header()
    resp = await client.post("/api/v1/agents", json={"name": "Buddy", "provider": ""}, headers=headers)
    assert resp.status_code == 201
    agent = resp.json()
    assert agent["name"] == "Buddy"
    assert agent["status"] == "inactive"

    resp = await client.get(f"/api/v1/agents/{agent['id']}", headers=headers)
    assert resp.status_code == 200
    assert resp.json()["id"] == agent["id"]


@pytest.mark.asyncio
async def test_list_agents_scoped_to_owner(client, auth_header):
    headers_a = auth_header()
    headers_b = auth_header()

    await client.post("/api/v1/agents", json={"name": "A's agent"}, headers=headers_a)
    await client.post("/api/v1/agents", json={"name": "B's agent"}, headers=headers_b)

    resp_a = await client.get("/api/v1/agents", headers=headers_a)
    names = [a["name"] for a in resp_a.json()]
    assert names == ["A's agent"]


@pytest.mark.asyncio
async def test_cannot_read_another_users_agent(client, auth_header):
    owner_headers = auth_header()
    other_headers = auth_header()

    create_resp = await client.post("/api/v1/agents", json={"name": "Secret agent"}, headers=owner_headers)
    agent_id = create_resp.json()["id"]

    resp = await client.get(f"/api/v1/agents/{agent_id}", headers=other_headers)
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_cannot_modify_another_users_agent(client, auth_header):
    owner_headers = auth_header()
    other_headers = auth_header()

    create_resp = await client.post("/api/v1/agents", json={"name": "Secret agent"}, headers=owner_headers)
    agent_id = create_resp.json()["id"]

    resp = await client.patch(f"/api/v1/agents/{agent_id}", json={"name": "Hijacked"}, headers=other_headers)
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_unknown_agent_is_404(client, auth_header):
    resp = await client.get(f"/api/v1/agents/{uuid.uuid4()}", headers=auth_header())
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_patch_agent_disables_and_audits(client, auth_header):
    headers = auth_header()
    create_resp = await client.post("/api/v1/agents", json={"name": "Buddy"}, headers=headers)
    agent_id = create_resp.json()["id"]

    resp = await client.patch(f"/api/v1/agents/{agent_id}", json={"status": "disabled"}, headers=headers)
    assert resp.status_code == 200
    assert resp.json()["status"] == "disabled"


# --- Identity ------------------------------------------------------------------


@pytest.mark.asyncio
async def test_create_agent_identity(client, auth_header):
    headers = auth_header()
    agent = (await client.post("/api/v1/agents", json={"name": "Buddy", "provider": ""}, headers=headers)).json()

    resp = await client.post(f"/api/v1/agents/{agent['id']}/identity", json={}, headers=headers)
    assert resp.status_code == 201
    identity = resp.json()
    assert identity["agent_id"] == agent["id"]
    assert identity["status"] == "active"
    assert identity["identity_key"].startswith("agent::")


@pytest.mark.asyncio
async def test_assign_existing_identity_key(client, auth_header):
    headers = auth_header()
    agent = (await client.post("/api/v1/agents", json={"name": "Buddy"}, headers=headers)).json()

    resp = await client.post(
        f"/api/v1/agents/{agent['id']}/identity",
        json={"identity_key": "agent::mac"},
        headers=headers,
    )
    assert resp.status_code == 201
    assert resp.json()["identity_key"] == "agent::mac"


@pytest.mark.asyncio
async def test_second_identity_conflicts(client, auth_header):
    headers = auth_header()
    agent = (await client.post("/api/v1/agents", json={"name": "Buddy"}, headers=headers)).json()

    await client.post(f"/api/v1/agents/{agent['id']}/identity", json={}, headers=headers)
    resp = await client.post(f"/api/v1/agents/{agent['id']}/identity", json={}, headers=headers)
    assert resp.status_code == 409
