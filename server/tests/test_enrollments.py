from __future__ import annotations

import pytest


@pytest.mark.asyncio
async def test_enrollment_request_approve_creates_active_identity(client, auth_header):
    headers = auth_header()
    resp = await client.post(
        "/api/v1/agent-enrollments", json={"agent_name": "New Buddy"}, headers=headers
    )
    assert resp.status_code == 201
    enrollment = resp.json()
    assert enrollment["status"] == "pending"

    approve_resp = await client.post(
        f"/api/v1/agent-enrollments/{enrollment['id']}/approve", headers=headers
    )
    assert approve_resp.status_code == 200
    approved = approve_resp.json()
    assert approved["status"] == "approved"
    assert approved["resulting_agent_id"] is not None

    agent_resp = await client.get(f"/api/v1/agents/{approved['resulting_agent_id']}", headers=headers)
    assert agent_resp.status_code == 200
    assert agent_resp.json()["status"] == "active"


@pytest.mark.asyncio
async def test_enrollment_request_deny(client, auth_header):
    headers = auth_header()
    resp = await client.post(
        "/api/v1/agent-enrollments", json={"agent_name": "Sketchy Agent"}, headers=headers
    )
    enrollment = resp.json()

    deny_resp = await client.post(f"/api/v1/agent-enrollments/{enrollment['id']}/deny", headers=headers)
    assert deny_resp.status_code == 200
    denied = deny_resp.json()
    assert denied["status"] == "denied"
    assert denied["resulting_agent_id"] is None


@pytest.mark.asyncio
async def test_enrollment_scoped_to_owner(client, auth_header):
    owner_headers = auth_header()
    other_headers = auth_header()

    resp = await client.post(
        "/api/v1/agent-enrollments", json={"agent_name": "Buddy"}, headers=owner_headers
    )
    enrollment_id = resp.json()["id"]

    approve_resp = await client.post(
        f"/api/v1/agent-enrollments/{enrollment_id}/approve", headers=other_headers
    )
    assert approve_resp.status_code == 404


@pytest.mark.asyncio
async def test_cannot_decide_enrollment_twice(client, auth_header):
    headers = auth_header()
    resp = await client.post(
        "/api/v1/agent-enrollments", json={"agent_name": "Buddy"}, headers=headers
    )
    enrollment_id = resp.json()["id"]

    await client.post(f"/api/v1/agent-enrollments/{enrollment_id}/approve", headers=headers)
    second = await client.post(f"/api/v1/agent-enrollments/{enrollment_id}/approve", headers=headers)
    assert second.status_code == 409
