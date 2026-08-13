# SPDX-License-Identifier: MPL-2.0
"""User-owned, persisted system/security state -- no database required.

State names are user-extensible strings; only "normal" carries built-in meaning
as the starting state. Two names are recognized for lifecycle event naming:
"incident" and "lockdown" (see cloud.py for the events emitted on transition).
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from .files import atomic_write

DEFAULT_STATE = "normal"
SECURITY_STATES = ("incident", "lockdown")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class StateStore:
    def __init__(self, config_path: Path, default: str = DEFAULT_STATE):
        self.path = config_path.with_suffix(".state.json")
        self.default = default
        self._data = self._load()

    def _load(self) -> dict[str, Any]:
        empty = {"current": self.default, "reason": None, "actor": None, "history": []}
        if not self.path.exists(): return empty
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
            data.setdefault("current", self.default); data.setdefault("history", [])
            return data
        except (OSError, json.JSONDecodeError):
            return empty

    def get(self) -> str: return self._data["current"]

    def set(self, name: str, reason: str = "", actor_id: str | None = None) -> dict[str, Any]:
        previous = self._data["current"]
        entry = {"from": previous, "to": name, "reason": reason, "actor": actor_id, "at": _now()}
        self._data["current"] = name; self._data["reason"] = reason; self._data["actor"] = actor_id
        self._data["history"] = (self._data.get("history", []) + [entry])[-50:]
        atomic_write(self.path,json.dumps(self._data, indent=2) + "\n")
        return entry

    def status(self) -> dict[str, Any]:
        return {"current": self._data["current"], "reason": self._data.get("reason"), "actor": self._data.get("actor"), "history": self._data.get("history", [])}
