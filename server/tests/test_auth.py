from __future__ import annotations

from datetime import timedelta

import pytest
from cryptography.hazmat.primitives.asymmetric import ec

from tests.conftest import make_token


@pytest.mark.asyncio
async def test_health_no_auth(client):
    resp = await client.get("/api/v1/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


@pytest.mark.asyncio
async def test_missing_token_rejected(client):
    resp = await client.get("/api/v1/me")
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_malformed_token_rejected(client):
    resp = await client.get("/api/v1/me", headers={"Authorization": "Bearer not-a-jwt"})
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_wrong_signing_key_rejected(client):
    # Signed with a DIFFERENT key than the one auth.py is configured to trust.
    other_key = ec.generate_private_key(ec.SECP256R1())
    token = make_token(key=other_key)
    resp = await client.get("/api/v1/me", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_expired_token_rejected(client):
    token = make_token(expires_in=timedelta(seconds=-60))
    resp = await client.get("/api/v1/me", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_wrong_audience_rejected(client):
    token = make_token(audience="some-other-app")
    resp = await client.get("/api/v1/me", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_valid_token_accepted(client, auth_header):
    resp = await client.get("/api/v1/me", headers=auth_header())
    assert resp.status_code == 200
