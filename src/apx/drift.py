# SPDX-License-Identifier: MIT
"""Change-drift detection.

APX only sees changes it makes itself through its own actions. Anything
changed by hand -- a table renamed in a dashboard, a config value edited
directly, another agent editing a file outside APX -- is invisible to it
until something downstream breaks. This module gives sources a place to
report their current shape; APX remembers the last shape it saw and tells
you exactly what changed, regardless of who changed it.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from platformdirs import user_data_path


def _store_dir() -> Path:
    path = user_data_path("apx") / "drift"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _safe_name(name: str) -> str:
    return "".join(c if c.isalnum() or c in "-_." else "_" for c in name)


def _snapshot_path(name: str) -> Path:
    return _store_dir() / f"{_safe_name(name)}.json"


def _log_path(name: str) -> Path:
    return _store_dir() / f"{_safe_name(name)}.log.jsonl"


def _fingerprint(payload: Any) -> str:
    canonical = json.dumps(payload, sort_keys=True, default=str)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _diff(before: Any, after: Any, path: str = "") -> list[dict[str, Any]]:
    changes: list[dict[str, Any]] = []
    if isinstance(before, dict) and isinstance(after, dict):
        for key in sorted(set(before) | set(after), key=str):
            sub = f"{path}.{key}" if path else str(key)
            if key not in before:
                changes.append({"path": sub, "kind": "added", "value": after[key]})
            elif key not in after:
                changes.append({"path": sub, "kind": "removed", "value": before[key]})
            else:
                changes.extend(_diff(before[key], after[key], sub))
    elif before != after:
        changes.append({"path": path or "$", "kind": "changed", "before": before, "after": after})
    return changes


@dataclass(frozen=True)
class DriftEvent:
    name: str
    detected_at: str
    previous_fingerprint: str | None
    fingerprint: str
    changes: list[dict[str, Any]]

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "detected_at": self.detected_at,
            "previous_fingerprint": self.previous_fingerprint,
            "fingerprint": self.fingerprint,
            "changes": self.changes,
        }


def check(name: str, payload: dict[str, Any]) -> dict[str, Any]:
    """Compare `payload` against the last recorded snapshot for `name`, then
    overwrite the snapshot with `payload` regardless of outcome. Returns
    whether drift was detected and, if so, an itemized diff of what changed."""
    path = _snapshot_path(name)
    fingerprint = _fingerprint(payload)
    now = datetime.now(timezone.utc).isoformat()
    previous = json.loads(path.read_text(encoding="utf-8")) if path.exists() else None

    path.write_text(json.dumps({"fingerprint": fingerprint, "payload": payload, "recorded_at": now}, indent=2), encoding="utf-8")

    if previous is None:
        return {"name": name, "drifted": False, "first_snapshot": True, "fingerprint": fingerprint}
    if previous["fingerprint"] == fingerprint:
        return {"name": name, "drifted": False, "first_snapshot": False, "fingerprint": fingerprint}

    event = DriftEvent(name=name, detected_at=now, previous_fingerprint=previous["fingerprint"], fingerprint=fingerprint, changes=_diff(previous["payload"], payload))
    with _log_path(name).open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(event.to_dict()) + "\n")
    return {"name": name, "drifted": True, "first_snapshot": False, "event": event.to_dict()}


def log(name: str, limit: int = 20) -> list[dict[str, Any]]:
    path = _log_path(name)
    if not path.exists():
        return []
    lines = path.read_text(encoding="utf-8").splitlines()
    return [json.loads(line) for line in lines[-limit:]]


def sources() -> list[str]:
    return sorted(p.stem for p in _store_dir().glob("*.json"))
