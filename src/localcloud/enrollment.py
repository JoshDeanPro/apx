"""Agent enrollment: an installed AI/machine/service asking for an identity, optionally
linked to OpenPower. Storage mirrors GroupStore/StateStore/MissionStore exactly -- one JSON
overlay file next to the config, whole-file load/save, no locking, no migrations.

Enrollment modes (configured via `[auth] enrollment_mode`, default "manual"):
  disabled       -- requests are refused outright (enforced by the caller, see cloud.py)
  manual         -- every request needs an explicit approve/deny
  trusted_device -- reserved for a future known-device fast path; behaves as manual today
  automatic      -- only ever applies when a user explicitly configures it (never the default)
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

MODES = ("disabled", "manual", "trusted_device", "automatic")
STATUSES = ("pending", "approved", "denied", "cancelled")


class EnrollmentError(RuntimeError): pass


def _now() -> str: return datetime.now(timezone.utc).isoformat()
def _id() -> str: return f"enr-{uuid4().hex[:8]}"


class EnrollmentStore:
    def __init__(self, config_path: Path):
        self.path = config_path.with_suffix(".enrollment.json")
        self._data = self._load()

    def _load(self) -> dict[str, Any]:
        if not self.path.exists(): return {"requests": {}}
        try:
            data = json.loads(self.path.read_text(encoding="utf-8")); data.setdefault("requests", {}); return data
        except (OSError, json.JSONDecodeError): return {"requests": {}}

    def _save(self) -> None: self.path.write_text(json.dumps(self._data, indent=2) + "\n", encoding="utf-8")

    def request(self, *, machine_id: str, runtime: str, mode: str = "manual", principal: str | None = None,
                requested_roles: list[str] | None = None, requested_scopes: list[str] | None = None,
                device_fingerprint: str | None = None) -> dict[str, Any]:
        if mode not in MODES: raise EnrollmentError(f"invalid enrollment mode {mode!r}")
        if mode == "disabled": raise EnrollmentError("agent enrollment is disabled by configuration")
        record = {
            "id": _id(), "principal": principal, "machine_id": machine_id, "runtime": runtime,
            "requested_roles": requested_roles or [], "requested_scopes": requested_scopes or [],
            "device_fingerprint": device_fingerprint, "mode": mode, "status": "pending",
            "created_at": _now(), "resolved_at": None, "resolved_by": None, "openpower_ref": None,
        }
        self._data["requests"][record["id"]] = record
        if mode == "automatic": self._resolve(record, "approved", resolved_by="automatic-policy")
        self._save()
        return record

    def get(self, request_id: str) -> dict[str, Any]:
        try: return self._data["requests"][request_id]
        except KeyError as error: raise EnrollmentError(f"unknown enrollment request {request_id!r}") from error

    def list(self, status: str | None = None) -> list[dict[str, Any]]:
        values = self._data["requests"].values()
        return sorted([r for r in values if status is None or r["status"] == status], key=lambda r: r["created_at"])

    def _resolve(self, record: dict[str, Any], status: str, *, resolved_by: str | None) -> dict[str, Any]:
        if record["status"] != "pending": raise EnrollmentError(f"enrollment request {record['id']!r} is already {record['status']}")
        record["status"] = status; record["resolved_at"] = _now(); record["resolved_by"] = resolved_by
        return record

    def approve(self, request_id: str, *, resolved_by: str | None = None, openpower_ref: str | None = None) -> dict[str, Any]:
        record = self._resolve(self.get(request_id), "approved", resolved_by=resolved_by)
        if openpower_ref: record["openpower_ref"] = openpower_ref
        self._save(); return record

    def deny(self, request_id: str, *, resolved_by: str | None = None) -> dict[str, Any]:
        record = self._resolve(self.get(request_id), "denied", resolved_by=resolved_by)
        self._save(); return record

    def cancel(self, request_id: str, *, resolved_by: str | None = None) -> dict[str, Any]:
        record = self._resolve(self.get(request_id), "cancelled", resolved_by=resolved_by)
        self._save(); return record
