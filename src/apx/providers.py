# SPDX-License-Identifier: MIT
"""Transport-neutral APX Action Provider SDK and conformance helpers."""
from __future__ import annotations

import json
import re
import urllib.parse
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable

from .actions import ActionRegistry, RegisteredAction
from .axp import (
    ACTION_RISKS, CONFIRMATION_LEVELS, PROVENANCE_KINDS,
    ActionDefinition, ActionReceipt, ActionRequest, ActionResult, ActorDescriptor,
    CredentialHandle, PreparedAction, Resource, StructuredError, ActionRequirements, APX_PROTOCOL_VERSION
)
from .credentials import SENSITIVE_KEYS
from .http import HTTPClient, HTTPFailure
from .health import ComponentHealth

def _public_value(value: Any, key: str = "") -> Any:
    lowered = key.lower()
    if lowered in {"default", "example", "examples", "value", "raw", "content"} or any(marker in lowered for marker in SENSITIVE_KEYS):
        return "<redacted>"
    if isinstance(value, dict):
        return {str(k): _public_value(v, str(k)) for k, v in value.items() if str(k).lower() not in {"authorization", "set-cookie", "cookie"}}
    if isinstance(value, (list, tuple)):
        return [_public_value(item, key) for item in value]
    if isinstance(value, str):
        return re.sub(r"(?i)(https?://)([^/@\s]+):([^/@\s]+)@", r"\1<redacted>@", value)
    return value


DISCOVERY_PATH = "/.well-known/apx"


class ProviderDiscoveryError(HTTPFailure, ValueError):
    """Structured discovery failure while retaining existing exception compatibility."""

    def __init__(self, message: str, structured_error: StructuredError):
        HTTPFailure.__init__(self, message, code=structured_error.code)
        self.structured_error = structured_error


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
    capabilities: tuple[str, ...] = ("discover", "prepare", "authorize", "execute", "status", "verify", "receipts", "cancel", "reverse")
    required_capabilities: tuple[str, ...] = ()
    optional_capabilities: tuple[str, ...] = ()
    required_credentials: tuple[str, ...] = ()
    required_permissions: tuple[str, ...] = ()
    allowed_actor_types: tuple[str, ...] = ()
    unavailable_actions: tuple[str, ...] = ()
    transports: tuple[dict[str, Any], ...] = ()
    apx_version: str = APX_PROTOCOL_VERSION
    manifest_version: str = APX_PROTOCOL_VERSION
    compatibility: tuple[str, ...] = (APX_PROTOCOL_VERSION,)
    profiles: tuple[str, ...] = ()
    metadata: dict[str, Any] = field(default_factory=dict)
    extensions: dict[str,str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.apx_version != APX_PROTOCOL_VERSION: raise ValueError(f"unsupported APX version {self.apx_version!r}")
        unknown=set(self.confirmation_methods)-set(CONFIRMATION_LEVELS)
        if unknown: raise ValueError(f"invalid confirmation methods: {sorted(unknown)}")
        ids=[action.id for action in self.actions]
        if len(ids)!=len(set(ids)): raise ValueError("provider action ids must be unique")
        from .personal import OPTIONAL_EXTENSIONS
        if set(self.extensions)-OPTIONAL_EXTENSIONS: raise ValueError("unknown optional extension")

    def to_dict(self) -> dict[str, Any]:
        """Serialize a manifest for a trusted local caller; protocol responses use `public_dict`."""
        return {
            "apx_version":self.apx_version,"manifest_version":self.manifest_version,
            "provider":asdict(self.provider),"resources":[item.to_dict() for item in self.resources],
            "actions":[item.to_dict() for item in self.actions],"authentication":list(self.authentication),
            "confirmation_methods":list(self.confirmation_methods),"capabilities":list(self.capabilities),
            "required_capabilities":list(self.required_capabilities),"optional_capabilities":list(self.optional_capabilities),
            "required_credentials":list(self.required_credentials),"required_permissions":list(self.required_permissions),
            "allowed_actor_types":list(self.allowed_actor_types),"unavailable_actions":list(self.unavailable_actions),
            "transports":list(self.transports),"compatibility":list(self.compatibility),
            "profiles":list(self.profiles),"metadata":self.metadata,"extensions":self.extensions,
        }

    def public_dict(self) -> dict[str, Any]:
        """Minimum-disclosure wire serialization for unauthenticated discovery."""
        value = self.to_dict()
        value["provider"] = {"id": self.provider.id, "name": self.provider.name, "provenance": self.provider.provenance}
        value["authentication"] = [_public_value(item) for item in self.authentication]
        value["actions"] = [_public_value(item.to_dict()) for item in self.actions]
        value["resources"] = [_public_value(item.to_dict()) for item in self.resources]
        value["required_credentials"] = ["credential_required"] if self.required_credentials else []
        value["metadata"] = {"version": self.metadata.get("version")} if self.metadata.get("version") is not None else {}
        value["transports"] = [{key: item[key] for key in ("type", "version", "protocol_endpoint") if key in item} for item in self.transports]
        return value

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "ProviderManifest":
        provider=ProviderIdentity(**value["provider"])
        actions=[]
        for raw in value.get("actions",[]):
            clean={k:v for k,v in raw.items() if k not in {"apx","axp","type","requirements"}}
            for key in ("side_effects","tags","postconditions"):
                if key in clean: clean[key]=tuple(clean[key])
            if "requirements" in raw:
                reqs = raw["requirements"]
                clean["requirements"] = __import__("apx").axp.ActionRequirements(
                    authentication_required=reqs.get("authentication_required", False),
                    permissions=tuple(reqs.get("permissions", ())),
                    approval_level=reqs.get("approval_level", "none"),
                    actor_types=tuple(reqs.get("actor_types", ())),
                    capabilities=tuple(reqs.get("capabilities", ())),
                    credentials=tuple(reqs.get("credentials", ())),
                    preconditions=tuple(reqs.get("preconditions", ())),
                )
            # Only keep keys that are fields of ActionDefinition
            from dataclasses import fields
            from .axp import ActionDefinition
            valid_keys = {f.name for f in fields(ActionDefinition)}
            unsupported = [k for k in clean if k not in valid_keys]
            legacy_keys = {"required_permissions", "credential_requirements", "actor_requirements", "preconditions"}
            unsupported_strict = [k for k in unsupported if k not in legacy_keys]
            if unsupported_strict:
                raise ValueError(f"Unknown keys in ActionDefinition: {unsupported_strict}")
            clean_filtered = {k: v for k, v in clean.items() if k in valid_keys}
            actions.append(ActionDefinition(**clean_filtered))
        resources=[]
        for raw in value.get("resources",[]):
            clean={k:v for k,v in raw.items() if k not in {"apx","axp","type","ref"}}
            for key in ("capabilities","groups","tags"):
                if key in clean: clean[key]=tuple(clean[key])
            resources.append(Resource(**clean))
        return cls(provider,tuple(actions),tuple(resources),tuple(value.get("authentication",())),
            tuple(value.get("confirmation_methods",())),tuple(value.get("capabilities",("discover","prepare","execute","receipts"))),
            tuple(value.get("required_capabilities",())),tuple(value.get("optional_capabilities",())),
            tuple(value.get("required_credentials",())),tuple(value.get("required_permissions",())),
            tuple(value.get("allowed_actor_types",())),tuple(value.get("unavailable_actions",())),
            tuple(value.get("transports",())),value.get("apx_version",APX_PROTOCOL_VERSION),value.get("manifest_version",APX_PROTOCOL_VERSION),
            tuple(value.get("compatibility",(APX_PROTOCOL_VERSION,))),tuple(value.get("profiles",())),value.get("metadata",{}),dict(value.get("extensions",{})))


@dataclass(frozen=True)
class CompatibilityResult:
    compatible: bool
    reasons: tuple[str, ...]
    errors: tuple[StructuredError, ...] = ()

    @property
    def error(self) -> StructuredError | None:
        return self.errors[0] if self.errors else None


def evaluate_compatibility(client_context: dict[str, Any], server_manifest: ProviderManifest) -> CompatibilityResult:
    reasons: list[str] = []
    errors: list[StructuredError] = []

    def add(code: str, reason: str, *, kind: str, name: str, retryable: bool = False) -> None:
        reasons.append(reason)
        errors.append(StructuredError(code, reason, details={"kind": kind, "name": name}, retryable=retryable))

    client_apx_version = client_context.get("apx_version", APX_PROTOCOL_VERSION)
    if server_manifest.apx_version != client_apx_version and client_apx_version not in server_manifest.compatibility:
        add("protocol_version_unsupported",
            f"incompatible protocol version: client {client_apx_version}, server {server_manifest.apx_version}",
            kind="protocol", name=server_manifest.apx_version)

    client_capabilities = set(client_context.get("capabilities", ()))
    for required in server_manifest.required_capabilities:
        if required not in client_capabilities:
            add("incompatible_requirements", f"required capability missing: {required}", kind="capability", name=required)

    server_capabilities = set(server_manifest.capabilities)
    for forbidden in client_context.get("forbidden_capabilities", ()):
        if forbidden in server_capabilities:
            add("incompatible_requirements", f"client forbids a server requirement: {forbidden}", kind="forbidden_capability", name=forbidden)

    server_actions = {action.id for action in server_manifest.actions if action.available}
    for required in client_context.get("required_actions", ()):
        if required not in server_actions:
            unavailable = required in server_manifest.unavailable_actions
            add("provider_unavailable" if unavailable else "incompatible_requirements",
                f"required action unavailable: {required}", kind="action", name=required, retryable=unavailable)

    client_credentials = set(client_context.get("authentication", ()))
    for required in server_manifest.required_credentials:
        if required not in client_credentials:
            add("incompatible_requirements", f"authentication unavailable: {required}", kind="credential", name=required)

    client_permissions = set(client_context.get("permissions", ()))
    for required in server_manifest.required_permissions:
        if required not in client_permissions:
            add("incompatible_requirements", f"permission unavailable: {required}", kind="permission", name=required)

    client_actor = client_context.get("actor_type", "unknown")
    if server_manifest.allowed_actor_types and client_actor not in server_manifest.allowed_actor_types:
        add("incompatible_requirements", f"actor type incompatible: {client_actor}", kind="actor", name=client_actor)

    return CompatibilityResult(not errors, tuple(reasons), tuple(errors))

@dataclass
class ProviderAction:
    registered: RegisteredAction


class ActionProvider:
    """Small SDK: define actions with decorators, then attach them to any APX registry."""
    def __init__(self, provider_id: str, name: str, *, url: str | None = None,
                 provenance: str = "native_provider", profiles: tuple[str, ...] = (),
                 authentication: tuple[dict[str, Any], ...] = (), metadata: dict[str, Any] | None = None,
                 extensions: tuple[str,...] = ()):
        self.identity=ProviderIdentity(provider_id,name,url,provenance)
        self.profiles=profiles; self.authentication=authentication; self.metadata=metadata or {}
        from .personal import OPTIONAL_EXTENSIONS
        if set(extensions)-OPTIONAL_EXTENSIONS: raise ValueError("unknown optional extension")
        self.extensions={name:"0.1" for name in extensions}; self.resources: list[Resource]=[]; self._actions: dict[str,ProviderAction]={}; self.receipts: dict[str,ActionReceipt]={}

    def resource(self, resource: Resource) -> Resource:
        self.resources.append(resource); return resource

    def action(self, action_id: str, *, description: str = "", input_schema: dict[str,Any] | None = None,
               output_schema: dict[str,Any] | None = None, resource_type: str | None = None,
               risk: str = "read", confirmation: str = "none", permissions: tuple[str,...] = (),
               reversible: bool = False, reverse_action: str | None = None,
               remediation_action: str | None = None, idempotent: bool | None = None,
               side_effects: tuple[str,...] = (), tags: tuple[str,...] = (),
               credentials: tuple[str,...] = (), actor_requirements: tuple[str,...] = (),
               expected_verification: str | None = None, version: str = "1.0",
               retry: str | None = None, preconditions: tuple[dict[str,Any],...] = (),
               postconditions: tuple[dict[str,Any],...] = (), constraints: dict[str,Any] | None = None,
               reversal_window: int | None = None, available: bool = True):
        if risk not in ACTION_RISKS: raise ValueError(f"invalid risk {risk!r}")
        if confirmation not in CONFIRMATION_LEVELS: raise ValueError(f"invalid confirmation {confirmation!r}")
        def decorate(handler: Callable[...,Any]):
            if action_id in self._actions: raise ValueError(f"duplicate action {action_id}")
            registered=RegisteredAction(
                name=action_id,
                description=description or (handler.__doc__ or action_id).strip(),
                handler=handler,
                schema=input_schema or {"type":"object","properties":{},"additionalProperties":False},
                read_only=risk=="read",
                destructive=risk in {"destructive","security_critical"},
                available=available,
                output_schema=output_schema,
                risk=risk,
                confirmation=confirmation,
                reversible=reversible,
                reverse_action=reverse_action,
                idempotent=idempotent,
                required_permissions=permissions,
                provider=self.identity.id,
                provenance=self.identity.provenance,
                tags=tags,
                version=version,
                deprecated=False,
                resource_type=resource_type,
                side_effects=side_effects,
                credential_requirements=credentials,
                actor_requirements=actor_requirements,
                expected_verification=expected_verification,
                remediation_action=remediation_action,
                retry=retry,
                preconditions=preconditions,
                postconditions=postconditions,
                constraints=constraints or {},
                reversal_window=reversal_window
            )
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
        transports=({"type":"http","version":APX_PROTOCOL_VERSION,"base_url":url,"protocol_endpoint":"/apx/v0.1"},) if url else ({"type":"local","version":APX_PROTOCOL_VERSION},)
        confirmations=tuple(sorted({a.confirmation for a in self.actions}))
        
        req_perms = set()
        req_creds = set()
        actor_types = set()
        unavailable = set()
        for a in self.actions:
            if not a.available: unavailable.add(a.name)
            req_perms.update(a.required_permissions)
            req_creds.update(a.credential_requirements)
            actor_types.update(a.actor_requirements)
            
        return ProviderManifest(self.identity,tuple(a.definition() for a in self.actions),tuple(self.resources),
            self.authentication,confirmations,
            required_permissions=tuple(sorted(req_perms)),
            required_credentials=tuple(sorted(req_creds)),
            allowed_actor_types=tuple(sorted(actor_types)),
            unavailable_actions=tuple(sorted(unavailable)),
            transports=transports,profiles=self.profiles,metadata=self.metadata,extensions=self.extensions)

    def register(self, registry: ActionRegistry) -> None:
        for action in self.actions: registry.register(action)

    def get_receipt(self, receipt_id: str) -> ActionReceipt | None: return self.receipts.get(receipt_id)
    def health(self)->ComponentHealth: return ComponentHealth(f"provider:{self.identity.id}","healthy",capabilities=tuple(self.manifest().capabilities),metadata={"actions":len(self.actions)})


def _contains_sensitive_key(value: Any) -> bool:
    if isinstance(value,dict):
        for key,item in value.items():
            lowered=key.lower()
            safe_metadata={"authentication","credential_requirements","credential_reference","credential_id","secret_input","secret_ref","x-apx-secret","required_credentials","credentials"}
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
    
    if set(manifest.required_capabilities) & set(manifest.optional_capabilities):
        errors.append("manifest declares overlapping required and optional capabilities")
        
    if isinstance(provider,ActionProvider):
        for action in provider.actions:
            if action.idempotent is None: errors.append(f"{action.name}: idempotency must be declared")
            if not callable(action.handler): errors.append(f"{action.name}: execution handler must be callable")
            
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
    def __init__(self, origin: str, manifest: ProviderManifest, *, client: HTTPClient|None=None):
        self.origin=origin.rstrip("/"); self._manifest=manifest; self.client=client or HTTPClient()

    @classmethod
    def discover(cls, origin: str, *, opener=None, client: HTTPClient|None=None, timeout: int = 10, client_context: dict[str,Any]|None=None) -> "RemoteProvider":
        parsed=urllib.parse.urlparse(origin)
        local=parsed.hostname in {"localhost","127.0.0.1","::1"}
        if parsed.scheme!="https" and not (parsed.scheme=="http" and local):
            raise ProviderDiscoveryError("remote APX discovery requires HTTPS", StructuredError(
                "connection_rejected", "remote APX discovery requires verified HTTPS",
                details={"kind":"transport"}))
        try:
            if opener is not None:
                response=opener(__import__("urllib.request",fromlist=["Request"]).Request(origin.rstrip("/")+DISCOVERY_PATH,headers={"Accept":"application/apx+json"}),timeout=timeout)
                raw=response.read(1024*1024+1)
            else:
                http=client or HTTPClient(); raw=http.request("GET",origin.rstrip("/")+DISCOVERY_PATH,headers={"Accept":"application/apx+json"},timeout=timeout).content
        except HTTPFailure as error:
            retryable=error.code in {"timeout","connection_failure"} or (error.status is not None and error.status >= 500)
            raise ProviderDiscoveryError("provider unavailable", StructuredError(
                "provider_unavailable", "provider unavailable",
                details={"kind":"transport", "transport_code":error.code, "status":error.status},
                retryable=retryable)) from error
        if len(raw)>1024*1024:
            raise ProviderDiscoveryError("provider manifest exceeds 1 MiB", StructuredError(
                "invalid_request", "provider manifest exceeds 1 MiB", details={"kind":"manifest"}))
        try:
            manifest=ProviderManifest.from_dict(json.loads(raw))
        except (TypeError, ValueError, KeyError, json.JSONDecodeError) as error:
            raise ProviderDiscoveryError("invalid provider manifest", StructuredError(
                "invalid_request", "invalid provider manifest", details={"kind":"manifest"})) from error
        errors=validate_provider(manifest)
        if errors:
            raise ProviderDiscoveryError("invalid provider manifest", StructuredError(
                "invalid_request", "invalid provider manifest", details={"kind":"manifest"}))
        if client_context is not None:
            compatibility = evaluate_compatibility(client_context, manifest)
            if not compatibility.compatible:
                structured=compatibility.error or StructuredError(
                    "incompatible_requirements", "provider requirements are incompatible", details={"kind":"compatibility"})
                raise ProviderDiscoveryError("provider is incompatible: "+"; ".join(compatibility.reasons), structured)
        return cls(origin,manifest,client=client)

    def manifest(self) -> ProviderManifest: return self._manifest
    def health(self)->ComponentHealth: return ComponentHealth(f"provider:{self._manifest.provider.id}","healthy",capabilities=self._manifest.capabilities,metadata={"origin":self.origin,"actions":len(self._manifest.actions)})

    def _post(self, path: str, value: dict[str,Any]) -> dict[str,Any]:
        return self.client.request("POST",self.origin+path,json=value,headers={"Content-Type":"application/apx+json","Accept":"application/apx+json"},idempotent=False).json()

    def prepare_action(self, request: ActionRequest) -> dict[str,Any]: return self._post("/apx/actions/prepare",request.to_dict())
    def execute_action(self, request: ActionRequest) -> dict[str,Any]: return self._post("/apx/actions/execute",request.to_dict())


class HTTPProviderAdapter:
    """Framework-neutral handler usable from WSGI, ASGI, FastAPI, Flask, or tests."""
    def __init__(self, provider: ActionProvider, executor: Callable[[ActionRequest],ActionResult] | None = None,
                 preparer: Callable[...,PreparedAction] | None = None, *, session=None):
        self.provider=provider; self.executor=executor; self.preparer=preparer
        if session is None and (executor is None or preparer is None):
            from .runtime import ProviderSession
            session=ProviderSession(provider)
        self.session=session

    def handle(self, method: str, path: str, body: dict[str,Any] | None = None) -> tuple[int,dict[str,str],dict[str,Any]]:
        headers={"Content-Type":"application/apx+json","Cache-Control":"no-store"}
        if method=="GET" and path==DISCOVERY_PATH: return 200,headers,self.provider.manifest().public_dict()
        if method=="GET" and path.startswith("/apx/v0.1/status/"):
            result=self.session.status(path.rsplit("/",1)[-1]) if self.session else None
            return (200,headers,result.to_dict()) if result else (404,headers,{"error":{"code":"invalid_request","message":"request not found"}})
        if method=="GET" and path.startswith("/apx/v0.1/operations/"):
            result=self.session.operation_status(path.rsplit("/",1)[-1]) if self.session else None
            return (200,headers,result.to_dict()) if result else (404,headers,{"error":{"code":"invalid_request","message":"operation not found"}})
        if method=="GET" and path.startswith("/apx/v0.1/receipts/"):
            receipt=self.session.receipt(path.rsplit("/",1)[-1]) if self.session else self.provider.get_receipt(path.rsplit("/",1)[-1])
            return (200,headers,receipt.to_dict()) if receipt else (404,headers,{"error":{"code":"invalid_request","message":"receipt not found"}})
        if method=="GET" and path.startswith("/apx/receipts/"):
            receipt=self.provider.get_receipt(path.rsplit("/",1)[-1])
            return (200,headers,receipt.to_dict()) if receipt else (404,headers,{"error":{"code":"receipt.not_found"}})
        if method=="POST" and path in {"/apx/actions/prepare","/apx/actions/execute"}:
            try: request=ActionRequest.from_dict(body or {})
            except (TypeError,ValueError,KeyError): return 400,headers,{"error":{"code":"invalid_request","message":"request does not match the APX action request shape"}}
            if path.endswith("prepare"):
                prepared=self.preparer(request.action,actor=request.actor,target=request.target,**request.input)
                return 200,headers,prepared.to_dict()
            result=self.executor(request)
            if result.receipt: self.provider.receipts[result.receipt.receipt_id]=result.receipt
            status=200 if result.ok else (401 if result.status=="awaiting-approval" else 403 if result.error and result.error.code=="permission_denied" else 400)
            return status,headers,result.to_dict()
        if method=="POST" and path in {"/apx/v0.1/prepare","/apx/v0.1/execute"} and self.session:
            try: request=ActionRequest.from_dict(body or {})
            except (TypeError,ValueError,KeyError): return 400,headers,{"error":{"code":"invalid_request","message":"request does not match the APX action request shape"}}
            value=self.session.prepare(request) if path.endswith("prepare") else self.session.execute(request)
            return 200,headers,value.to_dict()
        if method=="POST" and path=="/apx/v0.1/authorize" and self.session:
            result=self.session.authorize((body or {}).get("prepared_action_id",""),(body or {}).get("confirmation",{}))
            return 200,headers,result.to_dict()
        if method=="POST" and path=="/apx/v0.1/cancel" and self.session:
            return 200,headers,self.session.cancel((body or {}).get("prepared_action_id","")).to_dict()
        if method=="POST" and path.startswith("/apx/v0.1/reverse/") and self.session:
            try: request=ActionRequest.from_dict(body or {})
            except (TypeError,ValueError,KeyError): return 400,headers,{"error":{"code":"invalid_request","message":"request does not match the APX action request shape"}}
            return 200,headers,self.session.reverse(path.rsplit("/",1)[-1],request).to_dict()
        return 404,headers,{"error":{"code":"not_found"}}
