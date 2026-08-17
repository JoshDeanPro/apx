# SPDX-License-Identifier: MIT
"""Prompt management: saved prompts, shared prompts, device/agent scoped prompts.

APX allows defining, sharing, and scoping prompts across devices, agents, and teams.
Prompts are stored in a persistent JSON overlay sibling file (`config.prompts.json`).
"""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

from .files import atomic_write


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass(frozen=True)
class PromptRecord:
    id: str
    title: str
    description: str
    content: str
    scope: str = "shared"  # "shared", "device", "agent"
    targets: tuple[str, ...] = ("all",)
    tags: tuple[str, ...] = ()
    created_at: str = field(default_factory=_now)
    updated_at: str = field(default_factory=_now)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


DEFAULT_PROMPTS: list[dict[str, Any]] = [
    {
        "id": "prompt_universal_assistant",
        "title": "Universal Fabric Assistant",
        "description": "Standard system instructions for APX capability routing and execution.",
        "content": "You are connected to an APX-enabled environment. Use available actions, inspect resources, and adhere to capability boundaries.",
        "scope": "shared",
        "targets": ["all"],
        "tags": ["system", "default", "fabric"],
    },
    {
        "id": "prompt_system_operator",
        "title": "System Diagnostics & Operations",
        "description": "Operate and troubleshoot host hardware, services, network, and logs.",
        "content": "Analyze node hardware, examine journal logs, check service statuses, and ensure operational health with minimal disruptive actions.",
        "scope": "device",
        "targets": ["local"],
        "tags": ["operations", "diagnostics", "host"],
    },
    {
        "id": "prompt_code_reviewer",
        "title": "Autonomous Code Reviewer",
        "description": "Examine git diffs, project blueprints, and compliance checks.",
        "content": "Inspect discovered projects, verify blueprints, analyze code modifications for safety and correctness, and provide structured feedback.",
        "scope": "agent",
        "targets": ["all"],
        "tags": ["code", "review", "quality"],
    },
    {
        "id": "prompt_cloud_operator",
        "title": "Cloud & Domain Infrastructure",
        "description": "Manage DNS records, domains, SSL/TLS, and edge configurations.",
        "content": "Use connected DNS and domain providers (e.g. Porkbun, Cloudflare) to inspect zones, manage records, and ensure correct routing.",
        "scope": "shared",
        "targets": ["all"],
        "tags": ["cloud", "dns", "domains"],
    },
]


class PromptStore:
    def __init__(self, config_path: Path):
        self.path = config_path.with_suffix(".prompts.json")
        self._data: dict[str, Any] = self._load()

    def _load(self) -> dict[str, Any]:
        if not self.path.exists():
            initial = {"prompts": {item["id"]: item for item in DEFAULT_PROMPTS}}
            try:
                self.path.parent.mkdir(parents=True, exist_ok=True)
                atomic_write(self.path, json.dumps(initial, indent=2) + "\n")
            except Exception:
                pass
            return initial

        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
            if "prompts" not in data or not data["prompts"]:
                data["prompts"] = {item["id"]: item for item in DEFAULT_PROMPTS}
                self._save(data)
            return data
        except (OSError, json.JSONDecodeError):
            return {"prompts": {item["id"]: item for item in DEFAULT_PROMPTS}}

    def _save(self, data: dict[str, Any] | None = None) -> None:
        if data is not None:
            self._data = data
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            atomic_write(self.path, json.dumps(self._data, indent=2) + "\n")
        except Exception:
            pass

    def list(self, scope: str | None = None, target: str | None = None) -> list[PromptRecord]:
        results: list[PromptRecord] = []
        for item in self._data.get("prompts", {}).values():
            rec = PromptRecord(
                id=item["id"],
                title=item.get("title", item["id"]),
                description=item.get("description", ""),
                content=item.get("content", ""),
                scope=item.get("scope", "shared"),
                targets=tuple(item.get("targets", ["all"])),
                tags=tuple(item.get("tags", ())),
                created_at=item.get("created_at", _now()),
                updated_at=item.get("updated_at", _now()),
            )
            if scope and rec.scope != scope:
                continue
            if target and ("all" not in rec.targets and target not in rec.targets):
                continue
            results.append(rec)
        return sorted(results, key=lambda p: p.title)

    def get(self, prompt_id: str) -> PromptRecord | None:
        item = self._data.get("prompts", {}).get(prompt_id)
        if not item:
            return None
        return PromptRecord(
            id=item["id"],
            title=item.get("title", item["id"]),
            description=item.get("description", ""),
            content=item.get("content", ""),
            scope=item.get("scope", "shared"),
            targets=tuple(item.get("targets", ["all"])),
            tags=tuple(item.get("tags", ())),
            created_at=item.get("created_at", _now()),
            updated_at=item.get("updated_at", _now()),
        )

    def create(
        self,
        title: str,
        content: str,
        description: str = "",
        scope: str = "shared",
        targets: list[str] | tuple[str, ...] | None = None,
        tags: list[str] | tuple[str, ...] | None = None,
    ) -> PromptRecord:
        prompt_id = f"prompt_{uuid4().hex[:8]}"
        now_ts = _now()
        record = PromptRecord(
            id=prompt_id,
            title=title,
            description=description,
            content=content,
            scope=scope,
            targets=tuple(targets or ["all"]),
            tags=tuple(tags or ()),
            created_at=now_ts,
            updated_at=now_ts,
        )
        self._data.setdefault("prompts", {})[prompt_id] = record.to_dict()
        self._save()
        return record

    def update(
        self,
        prompt_id: str,
        title: str | None = None,
        content: str | None = None,
        description: str | None = None,
        scope: str | None = None,
        targets: list[str] | tuple[str, ...] | None = None,
        tags: list[str] | tuple[str, ...] | None = None,
    ) -> PromptRecord:
        item = self._data.get("prompts", {}).get(prompt_id)
        if not item:
            raise KeyError(f"prompt {prompt_id!r} not found")
        if title is not None:
            item["title"] = title
        if content is not None:
            item["content"] = content
        if description is not None:
            item["description"] = description
        if scope is not None:
            item["scope"] = scope
        if targets is not None:
            item["targets"] = list(targets)
        if tags is not None:
            item["tags"] = list(tags)
        item["updated_at"] = _now()
        self._save()
        return self.get(prompt_id)  # type: ignore

    def assign(self, prompt_id: str, targets: list[str] | tuple[str, ...]) -> PromptRecord:
        return self.update(prompt_id, targets=targets)

    def delete(self, prompt_id: str) -> bool:
        if prompt_id in self._data.get("prompts", {}):
            del self._data["prompts"][prompt_id]
            self._save()
            return True
        return False
