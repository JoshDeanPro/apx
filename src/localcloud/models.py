from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass(frozen=True)
class Host:
    name: str
    transport: str
    target: str | None = None

    def to_dict(self) -> dict[str, Any]: return asdict(self)


@dataclass(frozen=True)
class Capability:
    name: str
    available: bool
    command: str | None = None
    version: str | None = None
    details: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]: return asdict(self)


@dataclass(frozen=True)
class ActionResult:
    action: str
    ok: bool
    data: Any = None
    error: str | None = None
    host: str | None = None

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

    def to_dict(self) -> dict[str, Any]: return asdict(self)

