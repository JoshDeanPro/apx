# SPDX-License-Identifier: MIT
"""Hierarchical Scoped Settings Engine for APX.

Supports inheritance and scoping:
Global / Shared
  ↳ Device Group
    ↳ Device
      ↳ Service
        ↳ Agent

Tracks inherited vs overridden values, scope source, and target assignments.
Persisted in `.shared_settings.json`.
"""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .files import atomic_write


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class ScopedSettingEntry:
    key: str
    value: Any
    description: str = ""
    scope: str = "shared"  # "shared", "group:<name>", "device:<name>", "service:<name>", "agent:<name>"
    targets: tuple[str, ...] = ("all",)
    updated_at: str = field(default_factory=_now)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


DEFAULT_SHARED_SETTINGS: dict[str, dict[str, Any]] = {
    "prompt_stack": {
        "value": "universal-assistant",
        "description": "Default prompt stack applied to agents and execution",
        "scope": "shared",
        "targets": ["all"],
    },
    "model_routing": {
        "value": "auto",
        "description": "LLM inference routing policy (auto, local_preferred, cloud_fallback)",
        "scope": "shared",
        "targets": ["all"],
    },
    "log_level": {
        "value": "info",
        "description": "Logging verbosity across nodes and services",
        "scope": "shared",
        "targets": ["all"],
    },
    "auto_discovery": {
        "value": True,
        "description": "Periodically probe hardware, network peers, and local services",
        "scope": "shared",
        "targets": ["all"],
    },
    "telemetry_mode": {
        "value": "local_only",
        "description": "Fabric telemetry mode (local_only, openpower_synced)",
        "scope": "shared",
        "targets": ["all"],
    },
    "max_parallel_tasks": {
        "value": 4,
        "description": "Maximum concurrent background operations per node",
        "scope": "shared",
        "targets": ["all"],
    },
    "secret_backend": {
        "value": "keychain",
        "description": "Primary secure storage for provider tokens and keys",
        "scope": "shared",
        "targets": ["all"],
    },
}


class SharedSettingsStore:
    def __init__(self, config_path: Path):
        self.path = config_path.with_suffix(".shared_settings.json")
        self._data: dict[str, Any] = self._load()

    def _load(self) -> dict[str, Any]:
        if not self.path.exists():
            initial = {
                "version": 1,
                "scopes": {
                    "shared": {k: v for k, v in DEFAULT_SHARED_SETTINGS.items()},
                },
            }
            try:
                self.path.parent.mkdir(parents=True, exist_ok=True)
                atomic_write(self.path, json.dumps(initial, indent=2) + "\n")
            except Exception:
                pass
            return initial

        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
            scopes = data.setdefault("scopes", {})
            shared = scopes.setdefault("shared", {})
            for k, v in DEFAULT_SHARED_SETTINGS.items():
                if k not in shared:
                    shared[k] = v
            return data
        except (OSError, json.JSONDecodeError):
            return {
                "version": 1,
                "scopes": {
                    "shared": {k: v for k, v in DEFAULT_SHARED_SETTINGS.items()},
                },
            }

    def _save(self) -> None:
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            atomic_write(self.path, json.dumps(self._data, indent=2) + "\n")
        except Exception:
            pass

    def get_effective(self, key: str, target_scope: str | None = None, group: str | None = None) -> dict[str, Any]:
        """Resolves setting inheritance.
        Target scope resolution hierarchy:
        1. target_scope (e.g. agent:assistant or device:local)
        2. group scope (if group provided, e.g. group:compute)
        3. shared scope (global fabric baseline)
        4. built-in default
        """
        scopes = self._data.get("scopes", {})
        shared_scope = scopes.get("shared", {})
        shared_entry = shared_scope.get(key, DEFAULT_SHARED_SETTINGS.get(key, {}))

        # Baseline value from shared
        effective_value = shared_entry.get("value")
        description = shared_entry.get("description", "")
        source_scope = "shared"
        inherited = False
        inherited_from = None
        overridden = False

        if target_scope and target_scope != "shared":
            # Check group level first if specified
            if group:
                group_scope_key = f"group:{group}" if not group.startswith("group:") else group
                group_entry = scopes.get(group_scope_key, {}).get(key)
                if group_entry is not None:
                    effective_value = group_entry.get("value") if isinstance(group_entry, dict) else group_entry
                    source_scope = group_scope_key
                    inherited = True
                    inherited_from = group_scope_key

            # Check direct target scope
            target_entry = scopes.get(target_scope, {}).get(key)
            if target_entry is not None:
                effective_value = target_entry.get("value") if isinstance(target_entry, dict) else target_entry
                source_scope = target_scope
                overridden = True
                inherited = False
                inherited_from = None
            elif not group or group_entry is None:
                inherited = True
                inherited_from = "shared"
        else:
            source_scope = "shared"

        targets = shared_entry.get("targets", ["all"])

        return {
            "key": key,
            "value": effective_value,
            "description": description,
            "source_scope": source_scope,
            "target_scope": target_scope or "shared",
            "inherited": inherited,
            "inherited_from": inherited_from,
            "overridden": overridden,
            "shared_value": shared_entry.get("value"),
            "targets": targets,
        }

    def set(
        self,
        key: str,
        value: Any,
        scope: str = "shared",
        description: str = "",
        targets: list[str] | tuple[str, ...] | None = None,
    ) -> dict[str, Any]:
        scopes = self._data.setdefault("scopes", {})
        scope_data = scopes.setdefault(scope, {})

        entry = {
            "value": value,
            "description": description or DEFAULT_SHARED_SETTINGS.get(key, {}).get("description", ""),
            "scope": scope,
            "targets": list(targets or ["all"]),
            "updated_at": _now(),
        }
        scope_data[key] = entry
        self._save()
        return entry

    def remove_override(self, key: str, scope: str) -> bool:
        if scope == "shared":
            return False
        scopes = self._data.get("scopes", {})
        if scope in scopes and key in scopes[scope]:
            del scopes[scope][key]
            if not scopes[scope]:
                del scopes[scope]
            self._save()
            return True
        return False

    def list_all(self, target_scope: str | None = None, group: str | None = None) -> list[dict[str, Any]]:
        all_keys = set(DEFAULT_SHARED_SETTINGS.keys())
        for scope_name, entries in self._data.get("scopes", {}).items():
            all_keys.update(entries.keys())

        results = []
        for key in sorted(all_keys):
            results.append(self.get_effective(key, target_scope=target_scope, group=group))
        return results
