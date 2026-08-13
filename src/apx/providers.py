"""Transport-neutral APX Action Provider SDK and conformance helpers."""
from __future__ import annotations

import json
import urllib.parse
import urllib.request
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable

from .actions import ActionRegistry, RegisteredAction
from .axp import (
    ACTION_RISKS, CONFIRMATION_LEVELS, PROVENANCE_KINDS, AXP_VERSION,
    ActionDefinition, ActionReceipt, ActionRequest, ActionResult, ActorDescriptor,
    CredentialHandle, PreparedAction, Resource, StructuredError,
)
from .credentials import SENSITIVE_KEYS

DISCOVERY_PATH = "/.well-known/apx"
TRANSPORT_VERSION = "0.1"


@dataclass(frozen=True)
class ProviderIdentity:
    id: str
    name: str
    url: str | None = None
    provenance: str = "native_provider"

    def __post_init__(self) -> None:
        if self.provenance not in PROVENANCE_KINDS: raise ValueError(f"invalid provider provenance {self.provenance!r}")


@dataclass(frozen=True)
class ProviderManifest:
    provider: ProviderIdentity
    actions: tuple[ActionDefinition, ...]
    resources: tuple[Resource, ...] = ()
    authentication: tuple[dict[str, Any], ...] = ()
    confirmation_methods: tuple[str, ...] = ()
    capabilities: tuple[str, ...] = ("discover", "prepare", "execute", "receipts")
    transports: tuple[dict[str, Any], ...] = ()
    apx_version: str = AXP_VERSION
    manifest_version: str = TRANSPORT_VERSION
    compatibility: tuple[str, ...] = (AXP_VERSION,)
    profiles: tuple[str, ...] = ()
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.apx_version != AXP_VERSION: raise ValueError(f"unsupported APX version {self.apx_version!r}")
        unknown=set(self.confirmation_methods)-set(CONFIRMATION_LEVELS)
        if unknown: raise ValueError(f"invalid confirmation methods: {sorted(unknown)}")
        ids=[action.id for action in self.actions]
        if len(ids)!=len(set(ids)): raise ValueError("provider action ids must be unique")

    def to_dict(self) -> dict[str, Any]:
        return {
            "apx_version":self.apx_version,"manifest_version":self.manifest_version,
            "provider":asdict(self.provider),"resources":[item.to_dict() for item in self.resources],
            "actions":[item.to_dict() for item in self.actions],"authentication":list(self.authentication),
            "confirmation_methods":list(self.confirmation_methods),"capabilities":list(self.capabilities),
            "transports":list(self.transports),"compatibility":list(self.compatibility),
            "profiles":list(self.profiles),"metadata":self.metadata,
        }

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "ProviderManifest":
        provider=ProviderIdentity(**value["provider"])
        actions=[]
        for raw in value.get("actions",[]):
            clean={k:v for k,v in raw.items() if k not in {"axp","type"}}
            for key in ("side_effects","required_permissions","tags","credential_requirements","actor_requirements"):
                if key in clean: clean[key]=tuple(clean[key])
            actions.append(ActionDefinition(**clean))
        resources=[]
        for raw in value.get("resources",[]):
            clean={k:v for k,v in raw.items() if k not in {"axp","type"}}
            for key in ("capabilities","groups","tags"):
                if key in clean: clean[key]=tuple(clean[key])
            resources.append(Resource(**clean))
        return cls(provider,tuple(actions),tuple(resources),tuple(value.get("authentication",())),
            tuple(value.get("confirmation_methods",())),tuple(value.get("capabilities",("discover","prepare","execute","receipts"))),
            tuple(value.get("transports",())),value.get("apx_version",AXP_VERSION),value.get("manifest_version",TRANSPORT_VERSION),
            tuple(value.get("compatibility",(AXP_VERSION,))),tuple(value.get("profiles",())),value.get("metadata",{}))


@dataclass
class ProviderAction:
    registered: RegisteredAction


class ActionProvider:
    """Small SDK: define actions with decorators, then attach them to any APX registry."""
    def __init__(self, provider_id: str, name: str, *, url: str | None = None,
                 provenance: str = "native_provider", profiles: tuple[str, ...] = (),
                 authentication: tuple[dict[str, Any], ...] = (), metadata: dict[str, Any] | None = None):
        self.identity=ProviderIdentity(provider_id,name,url,provenance)
        self.profiles=profiles; self.authentication=authentication; self.metadata=metadata or {}
        self.resources: list[Resource]=[]; self._actions: dict[str,ProviderAction]={}; self.receipts: dict[str,ActionReceipt]={}

    def resource(self, resource: Resource) -> Resource:
        self.resources.append(resource); return resource

    def action(self, action_id: str, *, description: str = "", input_schema: dict[str,Any] | None = None,
               output_schema: dict[str,Any] | None = None, resource_type: str | None = None,
               risk: str = "read", confirmation: str = "none", permissions: tuple[str,...] = (),
               reversible: bool = False, reverse_action: str | None = None,
               remediation_action: str | None = None, idempotent: bool | None = None,
               side_effects: tuple[str,...] = (), tags: tuple[str,...] = (),
               credentials: tuple[str,...] = (), actor_requirements: tuple[str,...] = (),
               expected_verification: str | None = None, version: str = "1.0"):
        if risk not in ACTION_RISKS: raise ValueError(f"invalid risk {risk!r}")
        if confirmation not in CONFIRMATION_LEVELS: raise ValueError(f"invalid confirmation {confirmation!r}")
        def decorate(handler: Callable[...,Any]):
            if action_id in self._actions: raise ValueError(f"duplicate action {action_id}")
            registered=RegisteredAction(action_id,description or (handler.__doc__ or action_id).strip(),handler,
                input_schema or {"type":"object","properties":{},"additionalProperties":False},risk=="read",
                risk in {"destructive","security_critical"},output_schema,risk,confirmation,reversible,reverse_action,
                idempotent,permissions,self.identity.id,self.identity.provenance,tags,version,False,resource_type,
                side_effects,credentials,actor_requirements,expected_verification,remediation_action)
            self._actions[action_id]=ProviderAction(registered)
            return handler
        return decorate

    def prepare(self, action_id: str):
        def decorate(handler: Callable[...,Any]):
            action=self._actions[action_id].registered
            object.__setattr__(action,"prepare_handler",handler)
            return handler
        return decorate

    def verify(self, action_id: str):
        def decorate(handler: Callable[...,Any]):
            action=self._actions[action_id].registered
            object.__setattr__(action,"verify_handler",handler)
            return handler
        return decorate

    @property
    def actions(self) -> tuple[RegisteredAction,...]: return tuple(item.registered for item in self._actions.values())

    def manifest(self, *, base_url: str | None = None) -> ProviderManifest:
        url=base_url or self.identity.url
        transports=({"type":"http","version":TRANSPORT_VERSION,"base_url":url},) if url else ({"type":"local","version":TRANSPORT_VERSION},)
        confirmations=tuple(sorted({a.confirmation for a in self.actions}))
        return ProviderManifest(self.identity,tuple(a.definition() for a in self.actions),tuple(self.resources),
            self.authentication,confirmations,transports=transports,profiles=self.profiles,metadata=self.metadata)

    def register(self, registry: ActionRegistry) -> None:
        for action in self.actions: registry.register(action)

    def get_receipt(self, receipt_id: str) -> ActionReceipt | None: return self.receipts.get(receipt_id)


def _contains_sensitive_key(value: Any) -> bool:
    if isinstance(value,dict):
        for key,item in value.items():
            lowered=key.lower()
            safe_metadata={"authentication","credential_requirements","credential_reference","credential_id","secret_input","secret_ref","x-apx-secret"}
            if lowered not in safe_metadata and not lowered.endswith(("_id","_ref")) and any(marker in lowered for marker in SENSITIVE_KEYS): return True
            if _contains_sensitive_key(item): return True
    if isinstance(value,(list,tuple)): return any(_contains_sensitive_key(item) for item in value)
    return False


def validate_provider(provider: ActionProvider | ProviderManifest) -> list[str]:
    manifest=provider.manifest() if isinstance(provider,ActionProvider) else provider
    errors=[]
    try: ProviderManifest.from_dict(manifest.to_dict())
    except (TypeError,ValueError,KeyError) as error: errors.append(f"manifest: {error}")
    if _contains_sensitive_key(manifest.to_dict()): errors.append("manifest contains a secret-shaped field")
    action_ids={action.id for action in manifest.actions}
    if isinstance(provider,ActionProvider):
        for action in provider.actions:
            if action.idempotent is None: errors.append(f"{action.name}: idempotency must be declared")
    for action in manifest.actions:
        if action.input_schema.get("type")!="object": errors.append(f"{action.id}: input schema must describe an object")
        if action.reversible and not action.reverse_action: errors.append(f"{action.id}: reversible action requires reverse_action")
        if action.reverse_action and action.reverse_action not in action_ids: errors.append(f"{action.id}: reverse_action is not exposed")
    if "apx-commerce" in manifest.profiles:
        starts={"subscription.start","subscription.purchase","subscription.resume"}&action_ids
        if starts and "subscription.cancel" not in action_ids: errors.append("apx-commerce: recurring enrollment requires subscription.cancel when cancellation is supported")
    return errors


class RemoteProvider:
    """Explicitly enrolled HTTP provider; discovery never implies trust or execution."""
    def __init__(self, origin: str, manifest: ProviderManifest, *, opener=None):
        self.origin=origin.rstrip("/"); self._manifest=manifest; self.opener=opener or urllib.request.urlopen

    @classmethod
    def discover(cls, origin: str, *, opener=None, timeout: int = 10) -> "RemoteProvider":
        parsed=urllib.parse.urlparse(origin)
        local=parsed.hostname in {"localhost","127.0.0.1","::1"}
        if parsed.scheme!="https" and not (parsed.scheme=="http" and local): raise ValueError("remote APX discovery requires HTTPS")
        open_fn=opener or urllib.request.urlopen
        request=urllib.request.Request(origin.rstrip("/")+DISCOVERY_PATH,headers={"Accept":"application/apx+json"})
        response=open_fn(request,timeout=timeout); raw=response.read(1024*1024+1)
        if len(raw)>1024*1024: raise ValueError("provider manifest exceeds 1 MiB")
        manifest=ProviderManifest.from_dict(json.loads(raw))
        errors=validate_provider(manifest)
        if errors: raise ValueError("invalid provider manifest: "+"; ".join(errors))
        return cls(origin,manifest,opener=open_fn)

    def manifest(self) -> ProviderManifest: return self._manifest

    def _post(self, path: str, value: dict[str,Any]) -> dict[str,Any]:
        request=urllib.request.Request(self.origin+path,data=json.dumps(value).encode(),method="POST",
            headers={"Content-Type":"application/apx+json","Accept":"application/apx+json"})
        return json.loads(self.opener(request,timeout=30).read(1024*1024))

    def prepare_action(self, request: ActionRequest) -> dict[str,Any]: return self._post("/apx/actions/prepare",request.to_dict())
    def execute_action(self, request: ActionRequest) -> dict[str,Any]: return self._post("/apx/actions/execute",request.to_dict())


class HTTPProviderAdapter:
    """Framework-neutral handler usable from WSGI, ASGI, FastAPI, Flask, or tests."""
    def __init__(self, provider: ActionProvider, executor: Callable[[ActionRequest],ActionResult], preparer: Callable[...,PreparedAction]):
        self.provider=provider; self.executor=executor; self.preparer=preparer

    def handle(self, method: str, path: str, body: dict[str,Any] | None = None) -> tuple[int,dict[str,str],dict[str,Any]]:
        headers={"Content-Type":"application/apx+json","Cache-Control":"no-store"}
        if method=="GET" and path==DISCOVERY_PATH: return 200,headers,self.provider.manifest().to_dict()
        if method=="GET" and path.startswith("/apx/receipts/"):
            receipt=self.provider.get_receipt(path.rsplit("/",1)[-1])
            return (200,headers,receipt.to_dict()) if receipt else (404,headers,{"error":{"code":"receipt.not_found"}})
        if method=="POST" and path in {"/apx/actions/prepare","/apx/actions/execute"}:
            try: request=ActionRequest.from_dict(body or {})
            except (TypeError,ValueError,KeyError) as error: return 400,headers,{"error":{"code":"invalid_request","message":str(error)}}
            if path.endswith("prepare"):
                prepared=self.preparer(request.action,actor=request.actor,target=request.target,**request.input)
                return 200,headers,prepared.to_dict()
            result=self.executor(request)
            if result.receipt: self.provider.receipts[result.receipt.receipt_id]=result.receipt
            status=200 if result.ok else (401 if result.status=="authorization_required" else 403 if result.error and result.error.code=="permission_denied" else 400)
            return status,headers,result.to_dict()
        return 404,headers,{"error":{"code":"not_found"}}
