from __future__ import annotations

import pytest

from openpower_api.config import get_settings


@pytest.mark.asyncio
async def test_enrollment_creation_is_rate_limited(client, auth_header, monkeypatch):
    get_settings.cache_clear()
    monkeypatch.setenv("OPENPOWER_RATE_LIMIT_MAX", "2")
    monkeypatch.setenv("OPENPOWER_RATE_LIMIT_WINDOW_SECONDS", "60")
    get_settings.cache_clear()

    headers = auth_header()
    for _ in range(2):
        resp = await client.post(
            "/api/v1/agent-enrollments", json={"agent_name": "Buddy"}, headers=headers
        )
        assert resp.status_code == 201

    resp = await client.post("/api/v1/agent-enrollments", json={"agent_name": "Buddy"}, headers=headers)
    assert resp.status_code == 429

    get_settings.cache_clear()
