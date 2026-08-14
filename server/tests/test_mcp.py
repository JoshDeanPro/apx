"""Exercises the AXP Buddy MCP server through the real MCP protocol (not
just its underlying Python functions) -- a genuine client session, over the
same streamable-HTTP transport a real MCP client uses, against the app
in-process via an ASGI transport (no real network port needed).
"""
from __future__ import annotations

import uuid
from contextlib import asynccontextmanager

import httpx2
import pytest
from fastapi import FastAPI
from mcp.client.session import ClientSession
from mcp.client.streamable_http import streamable_http_client
from mcp.server.transport_security import TransportSecuritySettings

from openpower_api import db
from openpower_api.credentials import generate_credential_id, generate_secret, hash_secret
from openpower_api.mcp_server import build_mcp_server, mcp_asgi_app


@asynccontextmanager
async def _running_app():
    """A fresh FastAPI app + MCPServer per test, with its lifespan entered
    and exited in the SAME task as the caller -- StreamableHTTPSessionManager
    wraps an anyio TaskGroup, whose cancel scope must exit in the task that
    entered it. Splitting enter/exit across a pytest-asyncio fixture's
    setup/teardown steps runs them in different tasks and raises
    "Attempted to exit cancel scope in a different task"; a plain
    async-with inside the test body (via this context manager) doesn't."""
    server = build_mcp_server()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        async with server.session_manager.run():
            yield

    app = FastAPI(lifespan=lifespan)
    # DNS-rebinding protection is on by default in production; disabled here
    # only because the in-process test client's Host header is "test".
    app.mount(
        "/api/mcp",
        mcp_asgi_app(server, transport_security=TransportSecuritySettings(enable_dns_rebinding_protection=False)),
    )
    async with app.router.lifespan_context(app):
        yield app


async def _make_agent_with_credential() -> tuple[str, str, str]:
    """Bypasses HTTP entirely -- inserts an owner/agent/credential straight
    into the test database, exactly what a real signed-up user would have
    after using the website's own credential-creation flow."""
    owner_id = uuid.uuid4()
    sessionmaker = db.get_sessionmaker()
    async with sessionmaker() as session:
        agent = db.AgentProfile(owner_id=owner_id, name="Test MCP agent", status="active")
        session.add(agent)
        await session.flush()

        plaintext = generate_secret()
        credential_id = generate_credential_id()
        credential = db.AgentCredential(
            agent_id=agent.id,
            owner_id=owner_id,
            credential_id=credential_id,
            secret_hash=hash_secret(plaintext),
        )
        session.add(credential)
        await session.commit()
    return str(owner_id), credential_id, plaintext


@pytest.mark.asyncio
async def test_missing_auth_rejected():
    async with _running_app() as app:
        async with httpx2.AsyncClient(transport=httpx2.ASGITransport(app=app), base_url="http://test") as http_client:
            resp = await http_client.post("/api/mcp/", json={"jsonrpc": "2.0", "id": 1, "method": "ping"})
        assert resp.status_code == 401


@pytest.mark.asyncio
async def test_bad_credential_rejected():
    async with _running_app() as app:
        async with httpx2.AsyncClient(
            transport=httpx2.ASGITransport(app=app),
            base_url="http://test",
            headers={"Authorization": "Bearer cred_doesnotexist:wrongsecret"},
        ) as http_client:
            resp = await http_client.post("/api/mcp/", json={"jsonrpc": "2.0", "id": 1, "method": "ping"})
        assert resp.status_code == 401


@pytest.mark.asyncio
async def test_valid_credential_can_list_tools_and_call_one():
    owner_id, credential_id, secret = await _make_agent_with_credential()
    async with _running_app() as app:
        http_client = httpx2.AsyncClient(
            transport=httpx2.ASGITransport(app=app),
            headers={"Authorization": f"Bearer {credential_id}:{secret}"},
        )
        async with http_client:
            async with streamable_http_client("http://test/api/mcp/", http_client=http_client) as (read, write):
                async with ClientSession(read, write) as session:
                    await session.initialize()
                    tools = await session.list_tools()
                    names = {t.name for t in tools.tools}
                    assert "list_projects" in names
                    assert "create_project" in names
                    assert "list_machines" in names

                    result = await session.call_tool("create_project", {"name": "From MCP"})
                    assert result.is_error is not True

                    listed = await session.call_tool("list_projects", {})
                    assert listed.is_error is not True


@pytest.mark.asyncio
async def test_tool_calls_are_scoped_to_the_calling_owner():
    owner_a_id, cred_a_id, secret_a = await _make_agent_with_credential()
    owner_b_id, cred_b_id, secret_b = await _make_agent_with_credential()

    async with _running_app() as app:

        async def create_project_as(credential_id: str, secret: str, name: str) -> None:
            http_client = httpx2.AsyncClient(
                transport=httpx2.ASGITransport(app=app),
                headers={"Authorization": f"Bearer {credential_id}:{secret}"},
            )
            async with http_client:
                async with streamable_http_client("http://test/api/mcp/", http_client=http_client) as (read, write):
                    async with ClientSession(read, write) as session:
                        await session.initialize()
                        await session.call_tool("create_project", {"name": name})

        async def list_projects_as(credential_id: str, secret: str) -> list[str]:
            http_client = httpx2.AsyncClient(
                transport=httpx2.ASGITransport(app=app),
                headers={"Authorization": f"Bearer {credential_id}:{secret}"},
            )
            async with http_client:
                async with streamable_http_client("http://test/api/mcp/", http_client=http_client) as (read, write):
                    async with ClientSession(read, write) as session:
                        await session.initialize()
                        result = await session.call_tool("list_projects", {})
                        return [c.text for c in result.content if hasattr(c, "text")]

        await create_project_as(cred_a_id, secret_a, "Owner A's project")

        owner_b_projects = await list_projects_as(cred_b_id, secret_b)
        combined = " ".join(owner_b_projects)
        assert "Owner A's project" not in combined
