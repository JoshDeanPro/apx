# SPDX-License-Identifier: MPL-2.0
"""Typed, transport-neutral structures for Action Exchange Protocol 0.1."""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

APX_PROTOCOL_VERSION = "0.1"
AXP_VERSION = APX_PROTOCOL_VERSION  # Deprecated Python alias; remove at APX 1.0.

VERSION_STATES = ("current","supported","deprecated","unsupported","unknown","update_available")

ACTOR_KINDS = ("human","host","machine","agent","service","automation","api","mcp","plugin")

# Action Providers: what a Resource/Provider can do (read a value) up to (move money or
# change security posture). Deliberately small -- risk metadata exists so a client can
# decide how much confirmation to demand, not to enumerate every possible operation.
ACTION_RISKS = ("read","low_change","account_change","destructive","financial","security_critical")

# How much fresh human presence/confirmation an Action's risk level demands before
# execution. "none" and "delegated" require no fresh confirmation (the actor already has
# standing/delegated permission); everything past "confirm" requires the caller to supply
# matching confirmation in the ActionRequest or APX returns action.authorization_required.
CONFIRMATION_LEVELS = ("none","delegated","confirm","step_up","transaction","security_critical")

# Action lifecycle states -- an ActionResult.status, not a second boolean bolted onto `ok`.
ACTION_STATUSES = (
    "requested", "prepared", "authorization_required", "authorized", "accepted",
    "executing", "pending", "running", "completed", "denied", "rejected",
    "cancelled", "expired", "failed", "partial", "verification_failed", "reversed",
)

RETRY_POLICIES = ("safe", "idempotency_required", "manual", "never")
STANDARD_ERROR_CODES = (
    "invalid_request", "unsupported_action", "unauthenticated", "permission_denied",
    "confirmation_required", "policy_denied", "precondition_failed", "state_conflict",
    "rate_limited", "cooldown_active", "resource_locked", "provider_unavailable",
    "expired", "cancelled", "execution_failed", "partial_failure",
    "verification_failed", "protocol_version_unsupported", "ambiguous_execution",
)

# Where an Action's implementation actually comes from -- lets a client tell "Discord's own
# native APX action" apart from "an AI clicking through a webpage" without APX Core knowing
# anything about either. Descriptive only; not a trust ranking APX itself enforces.
PROVENANCE_KINDS = (
    "native_apx", "native_provider", "official_api", "official_sdk",
    "standard_bridge", "local_native", "official_plugin", "community_plugin",
    "local_component", "generated_component", "browser_component",
    "browser_fallback", "computer_fallback",
)

EVENT_NAMES = ("policy.allowed","policy.denied","system.state_changed","security.incident_started","security.lockdown_started","security.lockdown_ended","security.break_glass_started","secret.updated","secret.rotated","secret.revoked","credential.rotation_started","credential.rotation_completed","credential.rotation_failed","actor.connected",
    "identity.authenticated","identity.authentication_failed","identity.enrollment_requested","identity.enrollment_approved","identity.enrollment_denied","identity.linked","identity.unlinked",
    "credential.created","credential.rotated","credential.revoked","agent.connected","agent.disconnected",
    "action.prepared","action.authorization_required","action.authorized","action.started","action.completed","action.failed","action.reversed",
    "provider.connected","provider.disconnected","provider.action_added","provider.action_removed")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass(frozen=True)
class StructuredError:
    code: str
    message: str
    details: dict[str, Any] = field(default_factory=dict)
    retryable: bool = False
    provider_code: str | None = None
    retry_after: int | None = None
    next_actions: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]: return asdict(self)

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "StructuredError":
        clean=dict(value)
        if "next_actions" in clean: clean["next_actions"]=tuple(clean["next_actions"])
        return cls(**clean)


@dataclass(frozen=True)
class Resource:
    id: str
    kind: str
    name: str
    attributes: dict[str, Any] = field(default_factory=dict)
    capabilities: tuple[str, ...] = ()
    groups: tuple[str, ...] = ()
    tags: tuple[str, ...] = ()
    version: "VersionInfo | None" = None

    def to_dict(self) -> dict[str, Any]:
        return {"apx":APX_PROTOCOL_VERSION,"type":"resource",**asdict(self)}


@dataclass(frozen=True)
class VersionInfo:
    installed: str | None = None
    configured: str | None = None
    detected: str | None = None
    api_family: str | None = None
    api_version: str | None = None
    supported: tuple[str, ...] = ()
    deprecated: tuple[str, ...] = ()
    recommended: str | None = None
    latest_known: str | None = None
    compatibility: str = "unknown"
    source: str = "configuration"
    notes: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if self.compatibility not in VERSION_STATES:
            raise ValueError(f"invalid compatibility state {self.compatibility!r}")

    def to_dict(self) -> dict[str, Any]:
        return {"apx":APX_PROTOCOL_VERSION,"type":"version.info",**asdict(self)}


@dataclass(frozen=True)
class ResourceRelationship:
    source: str
    relation: str
    target: str
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {"apx":APX_PROTOCOL_VERSION,"type":"resource.relationship",**asdict(self)}


@dataclass(frozen=True)
class Connection:
    id: str
    adapter: str
    resource: str | None = None
    credential: str | None = None
    options: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {"apx":APX_PROTOCOL_VERSION,"type":"connection",**asdict(self)}


@dataclass(frozen=True)
class Capability:
    id: str
    resource: str
    description: str = ""
    available: bool = True
    metadata: dict[str, Any] = field(default_factory=dict)
    actions: tuple[str, ...] = ()
    provenance: str = "local_native"
    reliability: float = 1.0
    source: str | None = None
    health: str = "healthy"

    def __post_init__(self) -> None:
        if self.provenance not in PROVENANCE_KINDS: raise ValueError(f"invalid provenance {self.provenance!r}")
        if not 0 <= self.reliability <= 1: raise ValueError("reliability must be between 0 and 1")

    def to_dict(self) -> dict[str, Any]:
        return {"apx":APX_PROTOCOL_VERSION,"type":"capability",**asdict(self)}


@dataclass(frozen=True)
class Actor:
    id: str
    kind: str
    display_name: str | None = None

    def __post_init__(self) -> None:
        if self.kind not in ACTOR_KINDS:
            raise ValueError(f"invalid actor kind {self.kind!r}")

    def to_dict(self) -> dict[str, Any]:
        return {"apx":APX_PROTOCOL_VERSION,"type":"actor",**asdict(self)}

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "Actor":
        if value.get("apx") != APX_PROTOCOL_VERSION or value.get("type") != "actor":
            raise ValueError("not an APX 0.1 actor")
        return cls(id=value["id"],kind=value["kind"],display_name=value.get("display_name"))


@dataclass(frozen=True)
class AuthContext:
    """Identity evidence for a request -- who the caller was proven to be, and how.

    Never carries a raw secret/token/password; only metadata about the authentication
    event itself. See auth.py for how this gets produced (LocalAuthProvider/AuthManager)
    and consumed (cloud.execute()). Authentication informs policy of *who* is asking;
    it never grants authority -- that stays entirely in PolicyEngine (policy.py).
    """
    principal_id: str
    principal_type: str
    authentication_method: str
    issuer: str = "local"
    credential_id: str | None = None
    device_id: str | None = None
    delegated_by: str | None = None
    authenticated_at: str = field(default_factory=_now)
    expires_at: str | None = None
    session_id: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {"apx":APX_PROTOCOL_VERSION,"type":"auth.context",**asdict(self)}

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "AuthContext":
        known={"principal_id","principal_type","authentication_method","issuer","credential_id","device_id","delegated_by","authenticated_at","expires_at","session_id"}
        return cls(**{key:value[key] for key in known if key in value})


@dataclass(frozen=True)
class PolicyDecision:
    allowed: bool
    actor: str
    action: str
    reason: str
    scope: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        return {"apx":APX_PROTOCOL_VERSION,"type":"policy.decision",**asdict(self)}


@dataclass(frozen=True)
class ActionDefinition:
    id: str
    description: str
    input_schema: dict[str, Any]
    read_only: bool = True
    destructive: bool = False
    # --- Action Providers: what it MEANS, not just how to call it -----------------
    output_schema: dict[str, Any] | None = None
    risk: str = "read"
    confirmation: str = "none"
    reversible: bool = False
    reverse_action: str | None = None
    idempotent: bool = True
    side_effects: tuple[str, ...] = ()
    required_permissions: tuple[str, ...] = ()
    provider: str | None = None
    provenance: str = "native_provider"
    tags: tuple[str, ...] = ()
    version: str = "1.0"
    deprecated: bool = False
    resource_type: str | None = None
    credential_requirements: tuple[str, ...] = ()
    actor_requirements: tuple[str, ...] = ()
    expected_verification: str | None = None
    remediation_action: str | None = None
    deprecation_message: str | None = None
    extensions: dict[str, Any] = field(default_factory=dict)
    retry: str | None = None
    preconditions: tuple[dict[str, Any], ...] = ()
    postconditions: tuple[dict[str, Any], ...] = ()
    constraints: dict[str, Any] = field(default_factory=dict)
    reversal_window: int | None = None

    def __post_init__(self) -> None:
        if self.risk not in ACTION_RISKS: raise ValueError(f"invalid risk {self.risk!r}; expected one of {ACTION_RISKS}")
        if self.confirmation not in CONFIRMATION_LEVELS: raise ValueError(f"invalid confirmation {self.confirmation!r}; expected one of {CONFIRMATION_LEVELS}")
        if self.provenance not in PROVENANCE_KINDS: raise ValueError(f"invalid provenance {self.provenance!r}; expected one of {PROVENANCE_KINDS}")
        policy = self.retry or ("safe" if self.read_only else "idempotency_required" if self.idempotent else "never")
        if policy not in RETRY_POLICIES: raise ValueError(f"invalid retry policy {policy!r}")

    def to_dict(self) -> dict[str, Any]:
        return {"apx":APX_PROTOCOL_VERSION,"type":"action.definition",**asdict(self)}


@dataclass(frozen=True)
class ActionRequest:
    action: str
    target: dict[str, Any] = field(default_factory=dict)
    input: dict[str, Any] = field(default_factory=dict)
    request_id: str = field(default_factory=lambda: str(uuid4()))
    created_at: str = field(default_factory=_now)
    actor: str | None = None
    source: str | None = None
    correlation_id: str | None = None
    auth_context: dict[str, Any] | None = None
    # --- Action Providers: minimum-necessary delegation/confirmation envelope -----
    delegated_by: str | None = None
    client: str | None = None
    device: str | None = None
    mission: str | None = None
    confirmation: dict[str, Any] | None = None  # e.g. {"level": "confirm", "confirmed": true}
    expires_at: str | None = None
    nonce: str | None = None
    credential: "CredentialHandle | None" = None
    prepared_action_id: str | None = None
    idempotency_key: str | None = None
    authoritative_state_version: str | None = None
    protocol_version: str = AXP_VERSION

    def to_dict(self) -> dict[str, Any]:
        return {"apx":APX_PROTOCOL_VERSION,"type":"action.request",**asdict(self)}

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "ActionRequest":
        if value.get("apx") != APX_PROTOCOL_VERSION or value.get("type") != "action.request":
            raise ValueError("not an APX 0.1 action.request")
        known=("action","target","input","request_id","created_at","actor","source","correlation_id","auth_context","delegated_by","client","device","mission","confirmation","expires_at","nonce","prepared_action_id","idempotency_key","authoritative_state_version","protocol_version")
        values={key:value[key] for key in known if key in value}
        if value.get("credential"): values["credential"]=CredentialHandle.from_dict(value["credential"])
        return cls(**values)


@dataclass(frozen=True)
class ActionReceipt:
    """Structured proof a consequential Action actually happened -- so a caller never has
    to infer success from an HTTP 200 or a UI element disappearing. No secrets ever."""
    action: str
    provider: str | None
    target: dict[str, Any] = field(default_factory=dict)
    actor: str | None = None
    status: str = "completed"
    result: Any = None
    receipt_id: str = field(default_factory=lambda: str(uuid4()))
    request_id: str | None = None
    effective_time: str = field(default_factory=_now)
    verification_status: str = "unverified"
    reversible: bool = False
    reverse_action: str | None = None
    provider_reference: str | None = None
    side_effects: tuple[str, ...] = ()
    reversal: dict[str, Any] | None = None
    timestamp: str = field(default_factory=_now)
    delegated_by: str | None = None
    prepared_action_id: str | None = None
    committed_at: str | None = None
    completed_at: str | None = None
    verified_state: dict[str, Any] | None = None
    postconditions: tuple[dict[str, Any], ...] = ()
    partial_effects: tuple[dict[str, Any], ...] = ()

    def __post_init__(self) -> None:
        if self.status not in ACTION_STATUSES: raise ValueError(f"invalid receipt status {self.status!r}; expected one of {ACTION_STATUSES}")

    def to_dict(self) -> dict[str, Any]:
        return {"apx":APX_PROTOCOL_VERSION,"type":"action.receipt",**asdict(self)}


@dataclass(frozen=True)
class ActionResult:
    action: str
    ok: bool
    result: Any = None
    error: StructuredError | None = None
    request_id: str | None = None
    target: dict[str, Any] = field(default_factory=dict)
    status: str = "completed"
    receipt: ActionReceipt | None = None

    def __post_init__(self) -> None:
        if self.status not in ACTION_STATUSES: raise ValueError(f"invalid status {self.status!r}; expected one of {ACTION_STATUSES}")

    @property
    def data(self) -> Any: return self.result

    @property
    def host(self) -> str | None: return self.target.get("host")

    def to_dict(self) -> dict[str, Any]:
        return {"apx":APX_PROTOCOL_VERSION,"type":"action.result","action":self.action,"request_id":self.request_id,"target":self.target,"ok":self.ok,"status":self.status,"result":self.result,"error":self.error.to_dict() if self.error else None,"receipt":self.receipt.to_dict() if self.receipt else None,"data":self.result,"host":self.host}

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "ActionResult":
        if value.get("apx") != APX_PROTOCOL_VERSION or value.get("type") != "action.result":
            raise ValueError("not an APX 0.1 action.result")
        error=StructuredError.from_dict(value["error"]) if value.get("error") else None
        receipt=None
        if value.get("receipt"):
            raw={k:v for k,v in value["receipt"].items() if k not in {"apx","axp","type"}}
            if "side_effects" in raw: raw["side_effects"]=tuple(raw["side_effects"])
            receipt=ActionReceipt(**raw)
        return cls(action=value["action"],ok=value["ok"],result=value.get("result"),error=error,request_id=value.get("request_id"),target=value.get("target",{}),status=value.get("status","completed"),receipt=receipt)


@dataclass(frozen=True)
class PreparedAction:
    """What PREPARE answers before EXECUTE commits to anything: the resolved effect,
    cost/terms if any, and exactly what confirmation executing it will require."""
    action: str
    target: dict[str, Any] = field(default_factory=dict)
    input: dict[str, Any] = field(default_factory=dict)
    effect: str = ""
    confirmation_required: str = "none"
    cost: dict[str, Any] | None = None
    reversible: bool = False
    reverse_action: str | None = None
    expires_at: str | None = None
    request_id: str = field(default_factory=lambda: str(uuid4()))
    provider: str | None = None
    side_effects: tuple[str, ...] = ()
    provider_conditions: tuple[str, ...] = ()
    recurring_terms: dict[str, Any] | None = None
    authorization: dict[str, Any] | None = None
    confirmation_terms: dict[str, Any] | None = None
    prepared_action_id: str = field(default_factory=lambda: "pa_" + uuid4().hex)
    created_at: str = field(default_factory=_now)
    authoritative_state_version: str | None = None
    authoritative_state: dict[str, Any] | None = None
    preconditions: tuple[dict[str, Any], ...] = ()
    resolved_terms: dict[str, Any] = field(default_factory=dict)
    status: str = "prepared"

    def __post_init__(self) -> None:
        if self.confirmation_required not in CONFIRMATION_LEVELS:
            raise ValueError(f"invalid confirmation_required {self.confirmation_required!r}; expected one of {CONFIRMATION_LEVELS}")

    def to_dict(self) -> dict[str, Any]:
        return {"apx":APX_PROTOCOL_VERSION,"type":"action.prepared",**asdict(self)}


@dataclass(frozen=True)
class ActorDescriptor:
    """Minimum-necessary actor identity a provider is told, deliberately excluding
    everything not relevant to evaluating this one Action -- no conversation, no
    unrelated profiles, no machine inventory, no memories."""
    kind: str
    id: str
    owner: str | None = None
    client: str | None = None
    device: str | None = None
    roles: tuple[str, ...] = ()
    delegated_by: str | None = None
    permissions: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if self.kind not in ACTOR_KINDS: raise ValueError(f"invalid actor kind {self.kind!r}")

    def to_dict(self) -> dict[str, Any]:
        return {"apx":APX_PROTOCOL_VERSION,"type":"actor.descriptor",**asdict(self)}


@dataclass(frozen=True)
class CredentialHandle:
    """Abstraction over how an actor proves itself to a provider -- deliberately never
    carries a raw secret/key. `mode='bearer'` is what APX implements today (see auth.py/
    credentials.py); `mode='proof_of_possession'` is the intended long-term shape for
    long-lived agents (private key stays on the originating device, requests are signed/
    bound to it) -- APX Core defines this abstraction and does not implement the signing
    scheme itself; no custom cryptography, no algorithm invented here."""
    id: str
    mode: str
    issuer: str
    audience: str
    fingerprint: str | None = None
    expires_at: str | None = None
    revoked: bool = False

    def __post_init__(self) -> None:
        if self.mode not in ("bearer","proof_of_possession"):
            raise ValueError(f"invalid credential mode {self.mode!r}")

    def to_dict(self) -> dict[str, Any]:
        return {"apx":APX_PROTOCOL_VERSION,"type":"credential.handle",**asdict(self)}

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "CredentialHandle":
        if value.get("type") not in (None,"credential.handle"): raise ValueError("not a credential handle")
        known=("id","mode","issuer","audience","fingerprint","expires_at","revoked")
        return cls(**{key:value[key] for key in known if key in value})


@dataclass(frozen=True)
class SecretInput:
    """Opaque reference to secret material delivered through a secure side channel."""
    reference: str
    purpose: str
    delivery: str = "provider_secure_input"

    def to_dict(self) -> dict[str, Any]:
        return {"apx":APX_PROTOCOL_VERSION,"type":"secret.input","reference":self.reference,"purpose":self.purpose,"delivery":self.delivery}


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
        return {"apx":APX_PROTOCOL_VERSION,"type":"event",**asdict(self)}

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "Event":
        if value.get("apx") != APX_PROTOCOL_VERSION or value.get("type") != "event": raise ValueError("not an APX 0.1 event")
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
        return {"apx":APX_PROTOCOL_VERSION,"type":"context",**asdict(self)}

    @classmethod
    def from_mapping(cls, id: str, scope: str, value: dict[str, Any]) -> "Context":
        known={"preferred_technologies","avoid_technologies","conventions","architecture","commands","relationships","deployment"}
        return cls(id=id,scope=scope,preferred_technologies=tuple(value.get("preferred_technologies",())),avoid_technologies=tuple(value.get("avoid_technologies",value.get("avoid",()))),conventions=tuple(value.get("conventions",())),architecture=tuple(value.get("architecture",())),commands=dict(value.get("commands",{})),relationships=tuple(value.get("relationships",())),deployment=dict(value.get("deployment",{})),extra={k:v for k,v in value.items() if k not in known and k!="avoid"})
