from __future__ import annotations

import pytest


async def _make_agent(client, headers, name="Buddy") -> str:
    resp = await client.post("/api/v1/agents", json={"name": name}, headers=headers)
    return resp.json()["id"]


@pytest.mark.asyncio
async def test_credentials_overview_empty(client, auth_header):
    resp = await client.get("/api/v1/credentials", headers=auth_header())
    assert resp.status_code == 200
    assert resp.json() == []


@pytest.mark.asyncio
async def test_credentials_overview_lists_across_agents(client, auth_header):
    headers = auth_header()
    agent_a = await _make_agent(client, headers, "Claude on Mac")
    agent_b = await _make_agent(client, headers, "Claude on VPS")
    await client.post(f"/api/v1/agents/{agent_a}/credentials", json={}, headers=headers)
    await client.post(f"/api/v1/agents/{agent_b}/credentials", json={}, headers=headers)

    resp = await client.get("/api/v1/credentials", headers=headers)
    assert resp.status_code == 200
    body = resp.json()
    assert len(body) == 2
    names = {c["agent_name"] for c in body}
    assert names == {"Claude on Mac", "Claude on VPS"}
    for c in body:
        assert "secret" not in c


@pytest.mark.asyncio
async def test_credentials_overview_scoped_to_owner(client, auth_header):
    owner_headers = auth_header()
    other_headers = auth_header()
    agent_id = await _make_agent(client, owner_headers)
    await client.post(f"/api/v1/agents/{agent_id}/credentials", json={}, headers=owner_headers)

    resp = await client.get("/api/v1/credentials", headers=other_headers)
    assert resp.status_code == 200
    assert resp.json() == []
