# SPDX-License-Identifier: MPL-2.0
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass(frozen=True)
class Host:
    name: str
    transport: str
    target: str | None = None
    connections: tuple[dict[str, Any], ...] = ()
    groups: tuple[str, ...] = ()
    tags: tuple[str, ...] = ()
    # Descriptive only (e.g. "development", "production", "agent-runtime") -- surfaced via
    # to_dict()/resource.list for humans and docs. NOT yet consulted by PolicyEngine; only
    # actor-level roles (identity.ActorRegistry/[[actors]]) are enforced today. A host-scoped
    # policy dimension keyed on these is plausible future work, not implemented.
    roles: tuple[str, ...] = ()
    # True when this entry describes the machine APX is currently running on. The
    # fleet topology is meant to be the same on every node, so exactly one host in
    # a loaded config is the self host and only that one may be reached over the
    # `local` adapter -- see config.resolve_self_host(). Without this, a config
    # copied from another machine executes that machine's commands here and
    # reports the answers under its name.
    is_self: bool = True

    def to_dict(self) -> dict[str, Any]: return asdict(self)


@dataclass(frozen=True)
class ProjectLocation:
    host: str
    path: str
    role: str = "source"


@dataclass(frozen=True)
class Project:
    name: str
    description: str = ""
    locations: tuple[ProjectLocation, ...] = ()
    services: tuple[str, ...] = ()
    domains: tuple[str, ...] = ()
    context: dict[str, Any] = field(default_factory=dict)
    groups: tuple[str, ...] = ()
    tags: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]: return asdict(self)
