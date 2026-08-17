# SPDX-License-Identifier: MIT
"""`apx serve`: expose this APX instance's full action registry over the same
HTTP Action Provider protocol (providers.py / spec/http.md) any other APX
system already knows how to discover and call -- so a website (or another apx
install, or a mobile app) can see and use everything this one has without a
bespoke REST API invented just for it. Discovery, schemas, execution, and
receipts are the same wire shape as any other Provider; a caller that already
knows how to talk to one APX Provider already knows how to talk to this.

Stdlib-only (http.server) -- no new dependency for a server whose whole job is
being a small, auditable, always-available surface, same reasoning as tui.py.

Security note, not a formality: this binds to loopback by default and enforces
the exact same PolicyEngine every other apx entrypoint (CLI, TUI, MCP) does --
it does not add a second, separate permission system for "the website." If no
`[[roles]]` are configured, policy is a no-op and every action is reachable
from anything that can open a socket to this port; that is already true of the
CLI on an unconfigured install, this does not make it any more or less true,
it just adds a second local transport that inherits the same trust boundary.
"""
from __future__ import annotations

import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

from .cloud import APX
from .providers import DISCOVERY_PATH, HTTPProviderAdapter, ProviderIdentity, ProviderManifest


class CloudProviderView:
    """Adapts the full apx action registry to the small shape HTTPProviderAdapter
    needs (`.manifest()`, `.receipts`, `.get_receipt()`) -- not a real
    ActionProvider (no single provider "owns" every action here), just enough
    surface to reuse the protocol handler every real APX Provider already uses."""

    def __init__(self, cloud: APX, *, name: str = "apx", url: str | None = None):
        self.cloud = cloud
        self.receipts: dict[str, Any] = {}
        self.identity = ProviderIdentity("apx.local", name, url=url, provenance="native_apx")

    def manifest(self) -> ProviderManifest:
        actions = tuple(action.definition() for action in self.cloud.actions.list())
        resources = tuple(self.cloud.resources())
        transports = ({"type": "http", "version": "0.1", "base_url": self.identity.url, "protocol_endpoint": "/apx/v0.1"},) if self.identity.url else ()
        return ProviderManifest(self.identity, actions, resources,
                                 capabilities=("discover", "prepare", "execute", "receipts"), transports=transports)

    def get_receipt(self, receipt_id: str) -> Any: return self.receipts.get(receipt_id)


# Browser callers only: a page served from these origins may fetch this loopback-bound
# server directly from client-side JS. This does not relax the server's actual authorization --
# every action still goes through the same PolicyEngine; CORS only decides which page origins a
# browser will let read the response.
DEFAULT_ALLOWED_ORIGINS = ("http://localhost:3000", "http://127.0.0.1:3000", "http://localhost:8080", "http://127.0.0.1:8080")


def make_handler(adapter: HTTPProviderAdapter, *, allowed_origins: tuple[str, ...] = DEFAULT_ALLOWED_ORIGINS) -> type[BaseHTTPRequestHandler]:
    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def _cors_headers(self) -> dict[str, str]:
            origin = self.headers.get("Origin")
            if origin and origin in allowed_origins:
                return {"Access-Control-Allow-Origin": origin, "Vary": "Origin",
                        "Access-Control-Allow-Methods": "GET, POST, OPTIONS",
                        "Access-Control-Allow-Headers": "Content-Type"}
            return {}

        def _respond(self, status: int, headers: dict[str, str], payload: Any) -> None:
            body = json.dumps(payload).encode("utf-8")
            self.send_response(status)
            for key, value in {**headers, **self._cors_headers()}.items(): self.send_header(key, value)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_OPTIONS(self) -> None:
            self.send_response(204)
            for key, value in self._cors_headers().items(): self.send_header(key, value)
            self.send_header("Content-Length", "0")
            self.end_headers()

        def do_GET(self) -> None:
            status, headers, payload = adapter.handle("GET", self.path)
            self._respond(status, headers, payload)

        def do_POST(self) -> None:
            raw_len = self.headers.get("Content-Length", "0")
            try:
                length = int(raw_len or 0)
            except ValueError:
                self._respond(400, {"Content-Type": "application/apx+json"},
                               {"error": {"code": "invalid_request", "message": "invalid Content-Length header"}})
                return
            if length < 0:
                self._respond(400, {"Content-Type": "application/apx+json"},
                               {"error": {"code": "invalid_request", "message": "negative Content-Length"}})
                return
            max_body = 10 * 1024 * 1024  # 10 MB limit
            if length > max_body:
                self._respond(413, {"Content-Type": "application/apx+json"},
                               {"error": {"code": "payload_too_large", "message": f"request body exceeds limit of {max_body} bytes"}})
                return
            raw = self.rfile.read(length) if length else b""
            try:
                body = json.loads(raw) if raw else {}
            except json.JSONDecodeError:
                self._respond(400, {"Content-Type": "application/apx+json"},
                               {"error": {"code": "invalid_request", "message": "malformed JSON body"}})
                return
            status, headers, payload = adapter.handle("POST", self.path, body)
            self._respond(status, headers, payload)


        def log_message(self, format: str, *args: Any) -> None:
            pass  # quiet by default -- apx's own Event log already records action.started/completed

    return Handler


def serve(cloud: APX, *, host: str = "127.0.0.1", port: int = 8420, allowed_origins: tuple[str, ...] = DEFAULT_ALLOWED_ORIGINS) -> None:
    view = CloudProviderView(cloud, url=f"http://{host}:{port}")
    adapter = HTTPProviderAdapter(view, executor=cloud.execute, preparer=cloud.prepare)
    server = ThreadingHTTPServer((host, port), make_handler(adapter, allowed_origins=allowed_origins))
    action_count = len(cloud.actions.list())
    print(f"apx: serving {action_count} actions over HTTP on http://{host}:{port} "
          f"(discovery at {DISCOVERY_PATH}) -- Ctrl-C to stop")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
