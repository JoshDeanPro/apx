# SPDX-License-Identifier: MIT
"""Core plugin exposing drift-detection as APX actions -- always on, no
credentials required, since it only ever compares payloads other actions
hand it against what was last recorded on disk."""
from __future__ import annotations

from typing import Any

from ..actions import RegisteredAction
from .. import drift as drift_store


class Plugin:
    name = "drift"
    description = "Detect and log drift in anything APX depends on but doesn't own the change to -- schemas, configs, external state -- regardless of who changed it."
    version = "1.0"

    def __init__(self, config: dict[str, Any] | None = None):
        self.config = config or {}

    @property
    def metadata(self):
        from ..plugins import PluginMetadata
        return PluginMetadata(self.name, self.version, self.description, actions=("drift.check", "drift.log", "drift.sources"))

    def setup(self, api) -> None:
        self.api = api
        check_schema = {"type": "object", "properties": {"name": {"type": "string"}, "payload": {"type": "object"}}, "required": ["name", "payload"], "additionalProperties": False}
        log_schema = {"type": "object", "properties": {"name": {"type": "string"}, "limit": {"type": "integer"}}, "required": ["name"], "additionalProperties": False}
        sources_schema = {"type": "object", "properties": {}, "additionalProperties": False}
        api.register_action(RegisteredAction("drift.check", "Snapshot a named payload and report what changed since the last time this name was checked", self._check, check_schema, False, False))
        api.register_action(RegisteredAction("drift.log", "Read recorded drift events for a named source, most recent last", self._log, log_schema, True, False))
        api.register_action(RegisteredAction("drift.sources", "List every named source that has a recorded snapshot", self._sources, sources_schema, True, False))

    def _check(self, name: str, payload: dict[str, Any]) -> dict[str, Any]:
        return drift_store.check(name, payload)

    def _log(self, name: str, limit: int = 20) -> dict[str, Any]:
        return {"name": name, "events": drift_store.log(name, limit)}

    def _sources(self) -> dict[str, Any]:
        return {"sources": drift_store.sources()}
