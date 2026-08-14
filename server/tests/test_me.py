from __future__ import annotations

import uuid

import pytest


@pytest.mark.asyncio
async def test_me_returns_authenticated_users_profile(client, auth_header):
    user_id = uuid.uuid4()
    resp = await client.get("/api/v1/me", headers=auth_header(user_id, email="alice@example.com"))
    assert resp.status_code == 200
    body = resp.json()
    assert body["id"] == str(user_id)
    assert body["email"] == "alice@example.com"


@pytest.mark.asyncio
async def test_me_isolated_per_user(client, auth_header):
    user_a = uuid.uuid4()
    user_b = uuid.uuid4()

    resp_a = await client.get("/api/v1/me", headers=auth_header(user_a))
    resp_b = await client.get("/api/v1/me", headers=auth_header(user_b))

    assert resp_a.json()["id"] == str(user_a)
    assert resp_b.json()["id"] == str(user_b)
    assert resp_a.json()["id"] != resp_b.json()["id"]
