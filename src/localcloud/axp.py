"""Typed, transport-neutral structures for Action Exchange Protocol 0.1."""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

AXP_VERSION = "0.1"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass(frozen=True)
class StructuredError:
    code: str
    message: str
    details: dict[str, Any] = field(default_factory=dict)
    retryable: bool = False

    def to_dict(self) -> dict[str, Any]: return asdict(self)

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "StructuredError": return cls(**value)


@dataclass(frozen=True)
class Resource:
    id: str
    kind: str
    name: str
    attributes: dict[str, Any] = field(default_factory=dict)
    capabilities: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {"axp":AXP_VERSION,"type":"resource",**asdict(self)}


@dataclass(frozen=True)
class Capability:
    id: str
    resource: str
    description: str = ""
    available: bool = True
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {"axp":AXP_VERSION,"type":"capability",**asdict(self)}


@dataclass(frozen=True)
class ActionDefinition:
    id: str
    description: str
    input_schema: dict[str, Any]
    read_only: bool = True
    destructive: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {"axp":AXP_VERSION,"type":"action.definition",**asdict(self)}


@dataclass(frozen=True)
class ActionRequest:
    action: str
    target: dict[str, Any] = field(default_factory=dict)
    input: dict[str, Any] = field(default_factory=dict)
    request_id: str = field(default_factory=lambda: str(uuid4()))
    created_at: str = field(default_factory=_now)

    def to_dict(self) -> dict[str, Any]:
        return {"axp":AXP_VERSION,"type":"action.request",**asdict(self)}

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "ActionRequest":
        if value.get("axp") != AXP_VERSION or value.get("type") != "action.request":
            raise ValueError("not an AXP 0.1 action.request")
        return cls(**{key:value[key] for key in ("action","target","input","request_id","created_at") if key in value})


@dataclass(frozen=True)
class ActionResult:
    action: str
    ok: bool
    result: Any = None
    error: StructuredError | None = None
    request_id: str | None = None
    target: dict[str, Any] = field(default_factory=dict)

    @property
    def data(self) -> Any: return self.result

    @property
    def host(self) -> str | None: return self.target.get("host")

    def to_dict(self) -> dict[str, Any]:
        return {"axp":AXP_VERSION,"type":"action.result","action":self.action,"request_id":self.request_id,"target":self.target,"ok":self.ok,"result":self.result,"error":self.error.to_dict() if self.error else None,"data":self.result,"host":self.host}

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "ActionResult":
        if value.get("axp") != AXP_VERSION or value.get("type") != "action.result":
            raise ValueError("not an AXP 0.1 action.result")
        error=StructuredError.from_dict(value["error"]) if value.get("error") else None
        return cls(action=value["action"],ok=value["ok"],result=value.get("result"),error=error,request_id=value.get("request_id"),target=value.get("target",{}))


@dataclass(frozen=True)
class Event:
    name: str
    source: str
    subject: dict[str, Any] = field(default_factory=dict)
    data: dict[str, Any] = field(default_factory=dict)
    event_id: str = field(default_factory=lambda: str(uuid4()))
    occurred_at: str = field(default_factory=_now)
    correlation_id: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {"axp":AXP_VERSION,"type":"event",**asdict(self)}

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "Event":
        if value.get("axp") != AXP_VERSION or value.get("type") != "event": raise ValueError("not an AXP 0.1 event")
        return cls(**{key:value[key] for key in ("name","source","subject","data","event_id","occurred_at","correlation_id") if key in value})


@dataclass(frozen=True)
class Context:
    id: str
    scope: str
    preferred_technologies: tuple[str, ...] = ()
    avoid_technologies: tuple[str, ...] = ()
    conventions: tuple[str, ...] = ()
    architecture: tuple[str, ...] = ()
    commands: dict[str, str] = field(default_factory=dict)
    relationships: tuple[dict[str, Any], ...] = ()
    deployment: dict[str, Any] = field(default_factory=dict)
    extra: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {"axp":AXP_VERSION,"type":"context",**asdict(self)}

    @classmethod
    def from_mapping(cls, id: str, scope: str, value: dict[str, Any]) -> "Context":
        known={"preferred_technologies","avoid_technologies","conventions","architecture","commands","relationships","deployment"}
        return cls(id=id,scope=scope,preferred_technologies=tuple(value.get("preferred_technologies",())),avoid_technologies=tuple(value.get("avoid_technologies",value.get("avoid",()))),conventions=tuple(value.get("conventions",())),architecture=tuple(value.get("architecture",())),commands=dict(value.get("commands",{})),relationships=tuple(value.get("relationships",())),deployment=dict(value.get("deployment",{})),extra={k:v for k,v in value.items() if k not in known and k!="avoid"})
