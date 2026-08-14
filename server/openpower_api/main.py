"""OpenPower API entrypoint.

Runs as a plain ASGI app under uvicorn, bound to loopback only, behind an
existing Caddy reverse proxy at https://openpower.one/api/v1/... . Host/port
are env-var driven (see config.py / .env.example) so the systemd unit
(managed separately) controls the bind address without code changes.

Run with:
    python -m openpower_api.main
or:
    uvicorn openpower_api.main:app --host 127.0.0.1 --port 8100
"""
from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI

from .config import get_settings
from .mcp_server import build_mcp_server, mcp_asgi_app
from .routes import agent, agents, credentials, device, devices, enrollments, health, me

API_PREFIX = "/api/v1"

mcp_server = build_mcp_server()


@asynccontextmanager
async def lifespan(app: FastAPI):
    # The MCP session manager needs its own task group running for the
    # lifetime of the process -- mounting it as a sub-app doesn't start this
    # automatically, only the app's own lifespan does. Documented advanced
    # use case in mcp.server.mcpserver.MCPServer.session_manager.
    async with mcp_server.session_manager.run():
        yield


app = FastAPI(
    title="OpenPower API",
    description="Trusted application/API boundary for the OpenPower platform.",
    version="0.1.0",
    lifespan=lifespan,
)

app.include_router(health.router, prefix=API_PREFIX)
app.include_router(me.router, prefix=API_PREFIX)
app.include_router(agents.router, prefix=API_PREFIX)
app.include_router(enrollments.router, prefix=API_PREFIX)
app.include_router(device.router, prefix=API_PREFIX)
app.include_router(credentials.router, prefix=API_PREFIX)
app.include_router(agent.router, prefix=API_PREFIX)
app.include_router(devices.router, prefix=API_PREFIX)

# AXP MCP server -- https://openpower.one/api/mcp. Its own bearer-token
# auth middleware wraps it (see mcp_server.py); it deliberately isn't one of
# the Supabase-JWT-authenticated routers above.
app.mount("/api/mcp", mcp_asgi_app(mcp_server))


def run() -> None:
    import uvicorn

    settings = get_settings()
    uvicorn.run(
        "openpower_api.main:app",
        host=settings.openpower_api_host,
        port=settings.openpower_api_port,
        reload=False,
    )


if __name__ == "__main__":
    run()
