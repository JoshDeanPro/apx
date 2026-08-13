# SPDX-License-Identifier: MPL-2.0
"""AXP actor identity: who or what is calling an action."""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field, replace
from pathlib import Path
from typing import Any
from .files import atomic_write

from .axp import ACTOR_KINDS

DEFAULT_ACTOR = "human:local"


def parse_actor_id(actor_id: str) -> tuple[str, str]:
    """Split a canonical actor id (`kind:name[:host]`) into (kind, name)."""
    if not actor_id or ":" not in actor_id:
        raise ValueError(f"invalid actor id {actor_id!r}; expected kind:name")
    kind, name = actor_id.split(":", 1)
    if kind not in ACTOR_KINDS:
        raise ValueError(f"invalid actor kind {kind!r} in {actor_id!r}; expected one of {ACTOR_KINDS}")
    if not name:
        raise ValueError(f"invalid actor id {actor_id!r}; missing name")
    return kind, name


@dataclass(frozen=True)
class AgentProfile:
    """A registered actor: human, host, AI agent, service, automation, API/MCP client, or plugin."""
    id: str
    kind: str
    host: str | None = None
    runtime: str | None = None
    projects: tuple[str, ...] = ()
    roles: tuple[str, ...] = ()
    groups: tuple[str, ...] = ()
    tags: tuple[str, ...] = ()
    # Optional link to an OpenPower-side identity (e.g. "agent:<uuid>"). Metadata only --
    # never a password/token. The AI runtime (Claude/Codex/...) and this identity are
    # different concepts; changing runtime doesn't require changing this.
    openpower_identity: str | None = None

    def __post_init__(self) -> None:
        parsed_kind, _ = parse_actor_id(self.id)
        if parsed_kind != self.kind:
            raise ValueError(f"actor {self.id!r} kind mismatch: id says {parsed_kind!r}, kind is {self.kind!r}")

    def to_dict(self) -> dict[str, Any]: return asdict(self)


class ActorRegistry:
    """Actors declared under `[[actors]]`. Two agents of the same runtime on different hosts are different identities."""

    def __init__(self, actors: dict[str, AgentProfile] | None = None, default_actor: str = DEFAULT_ACTOR):
        self.actors = actors or {}
        self.default_actor = default_actor

    @classmethod
    def from_config(cls, raw: list[dict[str, Any]], default_actor: str = DEFAULT_ACTOR) -> "ActorRegistry":
        actors: dict[str, AgentProfile] = {}
        for item in raw:
            actor_id = item["id"]
            kind, _ = parse_actor_id(actor_id)
            actors[actor_id] = AgentProfile(
                id=actor_id, kind=item.get("kind", kind), host=item.get("host"), runtime=item.get("runtime"),
                projects=tuple(item.get("projects", ())), roles=tuple(item.get("roles", ())),
                groups=tuple(item.get("groups", ())), tags=tuple(item.get("tags", ())),
                openpower_identity=item.get("openpower_identity"),
            )
        return cls(actors, default_actor)

    def get(self, actor_id: str) -> AgentProfile | None:
        return self.actors.get(actor_id)

    def roles_for(self, actor_id: str) -> tuple[str, ...]:
        profile = self.get(actor_id)
        return profile.roles if profile else ()

    def resolve_default(self) -> str:
        return self.default_actor

    def list(self) -> list[AgentProfile]:
        return list(self.actors.values())


class IdentityLinkStore:
    """Persists identity.link/unlink (local actor <-> OpenPower subject) across restarts.
    Same JSON-overlay pattern as GroupStore/StateStore: a sibling file next to the config,
    applied as an overlay on top of whatever `[[actors]]` already declares."""

    def __init__(self, config_path: Path):
        self.path = config_path.with_suffix(".identity_links.json")
        self._data = self._load()

    def _load(self) -> dict[str, str]:
        if not self.path.exists(): return {}
        try: return json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError): return {}

    def _save(self) -> None: atomic_write(self.path,json.dumps(self._data, indent=2) + "\n")

    def apply(self, registry: ActorRegistry) -> None:
        for actor_id, openpower_identity in self._data.items():
            profile = registry.get(actor_id)
            if profile: registry.actors[actor_id] = replace(profile, openpower_identity=openpower_identity)

    def link(self, actor_id: str, openpower_identity: str, registry: ActorRegistry) -> None:
        self._data[actor_id] = openpower_identity; self._save(); self.apply(registry)

    def unlink(self, actor_id: str, registry: ActorRegistry) -> None:
        self._data.pop(actor_id, None); self._save()
        profile = registry.get(actor_id)
        if profile: registry.actors[actor_id] = replace(profile, openpower_identity=None)
