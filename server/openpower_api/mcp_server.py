"""AXP MCP server -- the official way an MCP client ( Desktop,
 Code, or anything else that speaks MCP) reaches a user's own OpenPower
data: Project Manager, Machines, Agents, Connections, Credentials metadata,
Prompts. Every tool call is scoped to exactly one owner_id, resolved from the
same Agent Credential bearer-secret system already used everywhere else in
this API -- there is no second auth mechanism to learn or configure.

Deliberately NOT using the MCP SDK's built-in OAuth resource-server support
(mcp.server.auth): that requires standing up a full OAuth authorization
server (issuer metadata, token endpoint, RFC 8414/9207/8707 discovery) to
authenticate a single static bearer token, which is a lot of moving parts
for what a human just pastes into a config file once. Instead, a small ASGI
middleware in front of the MCP app extracts `Authorization: Bearer
<credential_id>:<secret>`, verifies it with the exact same
`credentials.verify_credential` used by the human-facing credential
endpoints, and stashes the resolved owner_id in a contextvar every tool
reads. Simple, and there is exactly one credential system in this codebase,
not two.

`run_device_command` DOES reach a live machine: it queues a command in the
same `device_commands` table routes/agent.py's poll/report endpoints use,
and AXP (see LOCALCLOUD's `localcloud openpower run`) picks it up on its own
poll interval, executes it through its own policy-gated action dispatch, and
reports a result back here. The action is restricted to a fixed safe
allowlist (service status/restart, logs, host status) -- never arbitrary
shell. If that machine's AXP isn't currently running/polling, the command
just sits 'pending' until it is.
"""
from __future__ import annotations

import uuid
from contextvars import ContextVar
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Receive, Scope, Send

from mcp.server.mcpserver import MCPServer

from .credentials import verify_credential
from .db import (
    AgentCredential,
    AgentIdentity,
    AgentProfile,
    Device,
    DeviceCommand,
    Mission,
    Project,
    Prompt,
    ServiceConnection,
    get_sessionmaker,
)

_current_owner_id: ContextVar[uuid.UUID | None] = ContextVar("mcp_owner_id", default=None)


def _require_owner_id() -> uuid.UUID:
    owner_id = _current_owner_id.get()
    if owner_id is None:
        # Should be unreachable -- the auth middleware rejects unauthenticated
        # requests before they ever reach a tool call.
        raise RuntimeError("no authenticated owner for this MCP call")
    return owner_id


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if value else None


# --- Project Manager ---------------------------------------------------------


async def list_projects() -> list[dict[str, Any]]:
    """List this user's projects."""
    owner_id = _require_owner_id()
    async with get_sessionmaker()() as session:
        result = await session.execute(select(Project).where(Project.owner_id == owner_id))
        return [
            {"id": str(p.id), "name": p.name, "description": p.description, "status": p.status}
            for p in result.scalars().all()
        ]


async def create_project(name: str, description: str | None = None) -> dict[str, Any]:
    """Create a new project."""
    owner_id = _require_owner_id()
    async with get_sessionmaker()() as session:
        project = Project(owner_id=owner_id, name=name, description=description)
        session.add(project)
        await session.commit()
        await session.refresh(project)
        return {"id": str(project.id), "name": project.name, "status": project.status}


async def list_missions(project_id: str | None = None) -> list[dict[str, Any]]:
    """List missions (work items), optionally filtered to one project."""
    owner_id = _require_owner_id()
    async with get_sessionmaker()() as session:
        query = select(Mission).where(Mission.owner_id == owner_id)
        if project_id:
            query = query.where(Mission.project_id == uuid.UUID(project_id))
        result = await session.execute(query)
        return [
            {
                "id": str(m.id),
                "project_id": str(m.project_id),
                "title": m.title,
                "objective": m.objective,
                "status": m.status,
                "assigned_agent_id": str(m.assigned_agent_id) if m.assigned_agent_id else None,
            }
            for m in result.scalars().all()
        ]


async def create_mission(project_id: str, title: str, objective: str | None = None) -> dict[str, Any]:
    """Create a mission (a desired outcome) inside a project."""
    owner_id = _require_owner_id()
    async with get_sessionmaker()() as session:
        project = await session.execute(
            select(Project).where(Project.id == uuid.UUID(project_id), Project.owner_id == owner_id)
        )
        if project.scalar_one_or_none() is None:
            raise ValueError("project not found")
        mission = Mission(owner_id=owner_id, project_id=uuid.UUID(project_id), title=title, objective=objective)
        session.add(mission)
        await session.commit()
        await session.refresh(mission)
        return {"id": str(mission.id), "title": mission.title, "status": mission.status}


_MISSION_STATUSES = {"draft", "active", "blocked", "completed", "verified", "cancelled"}


async def update_mission_status(mission_id: str, status: str) -> dict[str, Any]:
    """Change a mission's status. One of: draft, active, blocked, completed, verified, cancelled."""
    owner_id = _require_owner_id()
    if status not in _MISSION_STATUSES:
        raise ValueError(f"status must be one of {sorted(_MISSION_STATUSES)}")
    async with get_sessionmaker()() as session:
        result = await session.execute(
            select(Mission).where(Mission.id == uuid.UUID(mission_id), Mission.owner_id == owner_id)
        )
        mission = result.scalar_one_or_none()
        if mission is None:
            raise ValueError("mission not found")
        mission.status = status
        await session.commit()
        return {"id": str(mission.id), "status": mission.status}


# --- Machines, Agents, Connections -------------------------------------------


async def list_machines() -> list[dict[str, Any]]:
    """List this user's machines. `status`/`last_seen` reflect the most
    recent heartbeat from that machine's own AXP instance, if it has ever
    linked and checked in -- devices added manually with no AXP running
    stay 'disconnected'."""
    owner_id = _require_owner_id()
    async with get_sessionmaker()() as session:
        result = await session.execute(select(Device).where(Device.owner_id == owner_id))
        return [
            {"id": str(d.id), "name": d.name, "type": d.type, "status": d.status, "last_seen": _iso(d.last_seen)}
            for d in result.scalars().all()
        ]


_ALLOWED_COMMAND_ACTIONS = {"service.status", "service.restart", "logs.read", "host.status"}


async def run_device_command(device_id: str, action: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
    """Queue a command on one of this user's machines and wait briefly for
    its AXP instance to pick it up and report a result. `action` must be one
    of: service.status, service.restart, logs.read, host.status -- this is a
    fixed safe allowlist, not arbitrary remote code execution. If the
    machine's AXP isn't currently polling (not running, or not linked),
    this returns status 'pending' -- check back with list_device_commands."""
    import asyncio

    owner_id = _require_owner_id()
    if action not in _ALLOWED_COMMAND_ACTIONS:
        raise ValueError(f"action must be one of {sorted(_ALLOWED_COMMAND_ACTIONS)}")

    async with get_sessionmaker()() as session:
        device = await session.execute(select(Device).where(Device.id == uuid.UUID(device_id), Device.owner_id == owner_id))
        if device.scalar_one_or_none() is None:
            raise ValueError("device not found")

        command = DeviceCommand(
            owner_id=owner_id, device_id=uuid.UUID(device_id), action=action, params=params or {}
        )
        session.add(command)
        await session.commit()
        await session.refresh(command)
        command_id = command.id

    # AXP polls on its own interval (not instant) -- wait briefly so a
    # human/agent calling this tool interactively usually sees the real
    # result rather than always having to call list_device_commands next.
    for _ in range(6):
        await asyncio.sleep(2)
        async with get_sessionmaker()() as session:
            result = await session.execute(select(DeviceCommand).where(DeviceCommand.id == command_id))
            command = result.scalar_one()
            if command.status in ("completed", "failed"):
                break

    return {
        "id": str(command.id),
        "status": command.status,
        "result": command.result,
        "error": command.error,
    }


async def list_device_commands(device_id: str) -> list[dict[str, Any]]:
    """List recent commands queued for one of this user's machines and their status/result."""
    owner_id = _require_owner_id()
    async with get_sessionmaker()() as session:
        result = await session.execute(
            select(DeviceCommand)
            .where(DeviceCommand.device_id == uuid.UUID(device_id), DeviceCommand.owner_id == owner_id)
            .order_by(DeviceCommand.created_at.desc())
            .limit(20)
        )
        return [
            {
                "id": str(c.id),
                "action": c.action,
                "status": c.status,
                "result": c.result,
                "error": c.error,
                "created_at": _iso(c.created_at),
            }
            for c in result.scalars().all()
        ]


async def list_agents() -> list[dict[str, Any]]:
    """List this user's AI agent profiles and their OpenPower identity, if any."""
    owner_id = _require_owner_id()
    async with get_sessionmaker()() as session:
        result = await session.execute(select(AgentProfile).where(AgentProfile.owner_id == owner_id))
        agents = result.scalars().all()
        identities = await session.execute(
            select(AgentIdentity).where(AgentIdentity.owner_id == owner_id)
        )
        by_agent = {i.agent_id: i.identity_key for i in identities.scalars().all()}
        return [
            {
                "id": str(a.id),
                "name": a.name,
                "provider": a.provider,
                "status": a.status,
                "identity_key": by_agent.get(a.id),
            }
            for a in agents
        ]


async def list_connections() -> list[dict[str, Any]]:
    """List this user's connected services (Cloudflare, OpenAI, Supabase, MCP servers, etc)."""
    owner_id = _require_owner_id()
    async with get_sessionmaker()() as session:
        result = await session.execute(select(ServiceConnection).where(ServiceConnection.owner_id == owner_id))
        return [{"id": str(s.id), "provider": s.provider, "status": s.status} for s in result.scalars().all()]


async def list_credentials() -> list[dict[str, Any]]:
    """List this user's agent credential metadata. Never returns a secret value."""
    owner_id = _require_owner_id()
    async with get_sessionmaker()() as session:
        result = await session.execute(
            select(AgentCredential, AgentProfile.name)
            .join(AgentProfile, AgentProfile.id == AgentCredential.agent_id)
            .where(AgentCredential.owner_id == owner_id)
        )
        return [
            {
                "credential_id": c.credential_id,
                "agent_name": name,
                "created_at": _iso(c.created_at),
                "last_used_at": _iso(c.last_used_at),
                "revoked_at": _iso(c.revoked_at),
            }
            for c, name in result.all()
        ]


# --- Prompts -------------------------------------------------------------------


async def list_prompts() -> list[dict[str, Any]]:
    """List this user's prompt library."""
    owner_id = _require_owner_id()
    async with get_sessionmaker()() as session:
        result = await session.execute(select(Prompt).where(Prompt.owner_id == owner_id))
        return [
            {"id": str(p.id), "name": p.name, "description": p.description, "tags": p.tags}
            for p in result.scalars().all()
        ]


async def create_prompt(
    name: str, content: str, description: str | None = None, tags: list[str] | None = None
) -> dict[str, Any]:
    """Add a prompt to this user's prompt library."""
    owner_id = _require_owner_id()
    async with get_sessionmaker()() as session:
        prompt = Prompt(owner_id=owner_id, name=name, content=content, description=description, tags=tags or [])
        session.add(prompt)
        await session.commit()
        await session.refresh(prompt)
        return {"id": str(prompt.id), "name": prompt.name}


# --- Auth middleware -----------------------------------------------------------


class BearerCredentialAuth:
    """Wraps the MCP ASGI app. Requires `Authorization: Bearer
    <credential_id>:<secret>` on every request, verified against the same
    AgentCredential store the website's own credential endpoints use.
    Rejects with 401 (never reaching the MCP app) on anything else."""

    def __init__(self, app: ASGIApp):
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        headers = dict(scope.get("headers") or [])
        auth_header = headers.get(b"authorization", b"").decode("latin-1")
        owner_id = await self._authenticate(auth_header)
        if owner_id is None:
            response = JSONResponse(
                {"error": "invalid_token", "detail": "Provide Authorization: Bearer <credential_id>:<secret>"},
                status_code=401,
                headers={"WWW-Authenticate": 'Bearer realm="AXP MCP"'},
            )
            await response(scope, receive, send)
            return

        token = _current_owner_id.set(owner_id)
        try:
            await self.app(scope, receive, send)
        finally:
            _current_owner_id.reset(token)

    async def _authenticate(self, auth_header: str) -> uuid.UUID | None:
        if not auth_header.lower().startswith("bearer "):
            return None
        raw = auth_header[7:].strip()
        if ":" not in raw:
            return None
        credential_id, secret = raw.split(":", 1)
        if not credential_id or not secret:
            return None

        async with get_sessionmaker()() as session:
            credential = await verify_credential(session, credential_id=credential_id, plaintext_secret=secret)
            if credential is None:
                return None
            credential.last_used_at = datetime.now(timezone.utc)
            await session.commit()
            return credential.owner_id


_TOOLS = (
    list_projects,
    create_project,
    list_missions,
    create_mission,
    update_mission_status,
    list_machines,
    list_agents,
    list_connections,
    list_credentials,
    list_prompts,
    create_prompt,
    run_device_command,
    list_device_commands,
)


def build_mcp_server() -> MCPServer:
    """A fresh MCPServer instance, tools registered. Factory rather than a
    module-level singleton because StreamableHTTPSessionManager.run() (which
    the app's lifespan enters) is single-use per instance -- tests that spin
    up their own app/lifespan need their own server, not one shared (and
    already spent) across the whole test session."""
    server = MCPServer(
        "OpenPower AXP",
        instructions=(
            "Reads and writes one user's own OpenPower data: their "
            "Project Manager (projects/missions), machine and agent records, "
            "connections, credential metadata, and prompt library. Scoped "
            "entirely to whichever account the connecting credential belongs "
            "to. run_device_command reaches a real machine if its AXP is "
            "linked and running, restricted to a fixed safe action allowlist."
        ),
    )
    for fn in _TOOLS:
        server.add_tool(fn)
    return server


def mcp_asgi_app(server: MCPServer, *, transport_security=None) -> ASGIApp:
    # streamable_http_path="/" so the endpoint lands exactly at the mount
    # point (/api/mcp), not the SDK's default /api/mcp/mcp. DNS-rebinding
    # protection (Host/Origin header allowlisting) stays on by default --
    # only tests override it, since their client sends Host: test.
    return BearerCredentialAuth(
        server.streamable_http_app(streamable_http_path="/", transport_security=transport_security)
    )
