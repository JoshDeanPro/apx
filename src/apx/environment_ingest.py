# SPDX-License-Identifier: MPL-2.0
"""Environment ingestion: read what other tools already have configured on this
machine -- their MCP servers, chiefly -- so apx does not require redeclaring an
integration that already exists elsewhere. `~/..json` ( Code) and
`~/.codex/config.toml` (Codex CLI) are both real, verified file formats read
directly off this machine, not guessed at.

Every source is independently enable/disable-able (`[ingest.<id>] enabled =
true` in apx.toml, default false -- opt-in, same as Providers/Plugins) and
always has a safe, side-effect-free "Information" probe (`probe()`) distinct
from actually importing anything (`mcp_servers()`, only ever called by
`environment.ingest`, which spawns real subprocesses to introspect each server
and so is never run implicitly at APX() construction time).
"""
from __future__ import annotations

import json
import tomllib
from pathlib import Path
from typing import Any


class IngestSource:
    id: str
    label: str
    verified: bool  # confirmed against a real file on a real machine, not guessed at

    def probe(self) -> dict[str, Any]: raise NotImplementedError
    def mcp_servers(self) -> dict[str, dict[str, Any]]: raise NotImplementedError


class CodeSource(IngestSource):
    id = "_code"; label = " Code (~/..json)"; verified = True

    def __init__(self, path: Path | None = None): self.path = path or Path.home()/"..json"

    def _data(self) -> dict[str, Any] | None:
        if not self.path.exists(): return None
        try: return json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError): return None

    def probe(self) -> dict[str, Any]:
        data = self._data()
        if not self.path.exists(): return {"id": self.id, "found": False}
        if data is None: return {"id": self.id, "found": True, "error": f"{self.path} could not be parsed"}
        servers = data.get("mcpServers") or {}
        return {"id": self.id, "found": True, "path": str(self.path), "mcp_server_count": len(servers), "mcp_servers": sorted(servers)}

    def mcp_servers(self) -> dict[str, dict[str, Any]]:
        data = self._data() or {}
        return {name: {"command": cfg.get("command"), "args": list(cfg.get("args") or ()), "env": dict(cfg.get("env") or {})}
                for name, cfg in (data.get("mcpServers") or {}).items()
                if cfg.get("type", "stdio") == "stdio" and cfg.get("command")}


class CodexSource(IngestSource):
    id = "codex"; label = "Codex CLI (~/.codex/config.toml)"; verified = True

    def __init__(self, path: Path | None = None): self.path = path or Path.home()/".codex/config.toml"

    def _data(self) -> dict[str, Any] | None:
        if not self.path.exists(): return None
        try: return tomllib.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, tomllib.TOMLDecodeError): return None

    def probe(self) -> dict[str, Any]:
        data = self._data()
        if not self.path.exists(): return {"id": self.id, "found": False}
        if data is None: return {"id": self.id, "found": True, "error": f"{self.path} could not be parsed"}
        servers = data.get("mcp_servers") or {}
        return {"id": self.id, "found": True, "path": str(self.path), "mcp_server_count": len(servers), "mcp_servers": sorted(servers)}

    def mcp_servers(self) -> dict[str, dict[str, Any]]:
        data = self._data() or {}
        return {name: {"command": cfg.get("command"), "args": list(cfg.get("args") or ()), "env": dict(cfg.get("env") or {})}
                for name, cfg in (data.get("mcp_servers") or {}).items() if cfg.get("command")}


SOURCES: dict[str, IngestSource] = {
    "_code": CodeSource(),
    "codex": CodexSource(),
}

# Not fabricated: none of these have a verified, on-disk config format confirmed
# on a real machine the way _code's and codex's were. "kimi_code" and
# "deepseek_code" were not found installed anywhere on this machine when
# checked; "personal_mcp" (a user's own hand-maintained MCP servers outside any
# specific agent's config) has no single canonical location to probe. Listed so
# `environment.sources` reports them honestly as not-yet-supported rather than
# omitting them and leaving "why doesn't apx see my Kimi config" unanswered.
PLANNED_SOURCES = ("kimi_code", "deepseek_code", "hermes", "personal_mcp")
