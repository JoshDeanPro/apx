# SPDX-License-Identifier: MPL-2.0
"""Hardware-aware Node profiles: cached, deterministic machine facts.

discovery.inspect_host() is a point-in-time probe -- every call re-runs a remote
script. NodeStore persists the result so APX (and agents reasoning about a Node)
never re-discover the same static facts (CPU, architecture, GPU, browsers, local
AI runtimes) on every question. Facts are cached with a TTL and only re-probed
when stale or explicitly forced -- "cache stable info, refresh changing state
sensibly" without per-field staleness tracking, which would be more machinery than
this actually needs.

Storage mirrors every other APX store: one JSON overlay file next to the config,
atomically replaced, no migrations, no database.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .discovery import inspect_host
from .files import atomic_write
from .models import Host

DEFAULT_TTL_SECONDS = 300


class NodeError(RuntimeError): pass


def _now() -> str: return datetime.now(timezone.utc).isoformat()


def _age_seconds(cached_at: str) -> float:
    try: cached = datetime.fromisoformat(cached_at)
    except ValueError: return float("inf")
    return (datetime.now(timezone.utc) - cached).total_seconds()


class NodeStore:
    def __init__(self, config_path: Path):
        self.path = config_path.with_suffix(".nodes.json")
        self._data = self._load()

    def _load(self) -> dict[str, Any]:
        empty = {"nodes": {}}
        if not self.path.exists(): return empty
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
            for key in empty: data.setdefault(key, {})
            return data
        except (OSError, json.JSONDecodeError):
            return empty

    def _save(self) -> None: atomic_write(self.path, json.dumps(self._data, indent=2) + "\n")

    def refresh(self, host: Host, *, force: bool = False, ttl_seconds: int = DEFAULT_TTL_SECONDS) -> dict[str, Any]:
        cached = self._data["nodes"].get(host.name)
        if cached and not force and _age_seconds(cached["cached_at"]) < cached.get("ttl_seconds", ttl_seconds):
            return cached
        try:
            profile = inspect_host(host)
        except Exception as error:
            if cached: return cached  # a stale-but-known profile beats no profile when a Node goes briefly unreachable
            raise NodeError(f"could not discover node {host.name!r}: {error}") from error
        record = {**profile, "cached_at": _now(), "ttl_seconds": ttl_seconds, "stale": False}
        self._data["nodes"][host.name] = record
        self._save()
        return record

    def get(self, name: str) -> dict[str, Any]:
        try: cached = dict(self._data["nodes"][name])
        except KeyError as error: raise NodeError(f"node {name!r} has not been discovered yet; run node.refresh first") from error
        cached["stale"] = _age_seconds(cached["cached_at"]) >= cached.get("ttl_seconds", DEFAULT_TTL_SECONDS)
        return cached

    def list(self) -> list[dict[str, Any]]:
        values = []
        for name in self._data["nodes"]:
            values.append(self.get(name))
        return sorted(values, key=lambda item: item["name"])
