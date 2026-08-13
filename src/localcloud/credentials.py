"""Replaceable credential references. Resolved values never leave this module."""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import urllib.error
import urllib.request
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable, Protocol
from uuid import uuid4

REDACTED="<redacted>"
SENSITIVE_KEYS=("token","secret","password","passwd","passphrase","api_key","apikey","private_key","client_secret","access_token","refresh_token","authorization","credential","cookie")
LIFECYCLE_STATES=("active","rotated","retired","revoked","destroyed","unknown")


class CredentialError(RuntimeError): pass


@dataclass(frozen=True)
class CredentialReference:
    id: str
    kind: str = "generic"
    source: str = "environment"
    reference: str = ""
    scopes: tuple[str,...] = ()
    description: str = ""
    metadata: dict[str,Any] = field(default_factory=dict)
    groups: tuple[str,...] = ()
    tags: tuple[str,...] = ()
    api_family: str | None = None
    api_version: str | None = None

    def to_dict(self) -> dict[str,Any]:
        return {"id":self.id,"kind":self.kind,"source":self.source,"reference":self.reference,"scopes":self.scopes,"description":self.description,"groups":self.groups,"tags":self.tags,"api_family":self.api_family,"api_version":self.api_version}


class CredentialRegistry:
    def __init__(self, references: dict[str,CredentialReference] | None = None): self.references=references or {}

    @classmethod
    def from_config(cls, values: dict[str,Any]) -> "CredentialRegistry":
        refs={}
        for name,value in values.items():
            known={"kind","provider","source","reference","scopes","description","groups","tags","api_family","api_version"}
            refs[name]=CredentialReference(id=name,kind=value.get("provider",value.get("kind",name)),source=value.get("source","environment"),reference=value.get("reference",""),scopes=tuple(value.get("scopes",())),description=value.get("description",""),metadata={k:v for k,v in value.items() if k not in known},groups=tuple(value.get("groups",())),tags=tuple(value.get("tags",())),api_family=value.get("api_family"),api_version=value.get("api_version"))
        return cls(refs)

    def get(self, credential_id: str) -> CredentialReference:
        try: return self.references[credential_id]
        except KeyError as error: raise CredentialError(f"credential reference {credential_id!r} is not configured") from error

    def resolve(self, credential_id: str) -> str:
        reference=self.get(credential_id)
        if reference.source!="environment": raise CredentialError(f"credential {credential_id!r} uses unsupported source {reference.source!r}")
        if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*",reference.reference): raise CredentialError(f"credential {credential_id!r} has an invalid environment reference")
        value=os.environ.get(reference.reference,"")
        if not value: raise CredentialError(f"credential {credential_id!r} is unavailable from its environment reference")
        return value

    def health(self) -> list[dict[str,Any]]:
        results=[]
        for reference in self.references.values():
            available=reference.source=="environment" and bool(os.environ.get(reference.reference,""))
            results.append({"id":reference.id,"kind":reference.kind,"configured":True,"available":available,"source":reference.source,"reference":reference.reference,"scopes":reference.scopes,"description":reference.description,"groups":reference.groups,"tags":reference.tags,"api_family":reference.api_family,"api_version":reference.api_version})
        return results

    def redact(self, value: Any) -> Any:
        known={os.environ.get(ref.reference) for ref in self.references.values() if ref.source=="environment" and os.environ.get(ref.reference)}
        def is_sensitive_key(key: str) -> bool:
            # "credential_id"/"secret_ref" etc name a REFERENCE, never the value itself
            # (this codebase's own convention throughout credentials.py) -- an "_id"/"_ref"
            # suffix means identifier, not secret, even though it contains a sensitive marker.
            lowered=key.lower()
            if lowered in {"id","ref"} or lowered.endswith(("_id","_ref")): return False
            return any(marker in lowered for marker in SENSITIVE_KEYS)
        def scrub(item: Any, key: str = "") -> Any:
            if isinstance(item,dict): return {k:(REDACTED if is_sensitive_key(k) and v not in (None,"") else scrub(v,k)) for k,v in item.items()}
            if isinstance(item,(list,tuple)): return [scrub(v,key) for v in item]
            if isinstance(item,str):
                for secret in known:
                    if secret in item:
                        item=item.replace(secret,REDACTED)
                return item
            return item
        return scrub(value)

    def redact_text(self, value: str) -> str:
        cleaned=value
        for reference in self.references.values():
            secret=os.environ.get(reference.reference) if reference.source=="environment" else None
            if secret: cleaned=cleaned.replace(secret,REDACTED)
        return cleaned


class SecretBackend(Protocol):
    """A pluggable place secret values may actually live. Capabilities are declared, never assumed."""
    name: str
    capabilities: frozenset[str]

    def health(self, ref: CredentialReference) -> dict[str, Any]: ...
    def reveal(self, ref: CredentialReference) -> str: ...
    def set(self, ref: CredentialReference, value: str) -> dict[str, Any]: ...


class SecretBackendError(RuntimeError): pass


class EnvironmentBackend:
    """Wraps the existing environment-variable resolution. Read-only: env vars are not durably settable here."""
    name="environment"
    capabilities=frozenset({"get","health"})

    def health(self, ref: CredentialReference) -> dict[str, Any]:
        available=bool(os.environ.get(ref.reference,""))
        return {"id":ref.id,"source":self.name,"available":available,"reference":ref.reference,"lifecycle":"active" if available else "unknown"}

    def reveal(self, ref: CredentialReference) -> str:
        if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*",ref.reference): raise SecretBackendError(f"credential {ref.id!r} has an invalid environment reference")
        value=os.environ.get(ref.reference,"")
        if not value: raise SecretBackendError(f"credential {ref.id!r} is unavailable from its environment reference")
        return value

    def set(self, ref: CredentialReference, value: str) -> dict[str, Any]:
        raise SecretBackendError("the environment backend cannot durably set values; export the variable in your shell/service manager instead")


class KeychainBackend:
    """macOS Keychain, via the stdlib-only `security` CLI (no new dependency). Darwin only."""
    name="keychain"
    capabilities=frozenset({"get","set","health"})
    service="localcloud"

    def __init__(self, run: Callable[..., subprocess.CompletedProcess] = subprocess.run):
        if sys.platform!="darwin": raise SecretBackendError("the keychain backend is only available on macOS")
        self._run=run

    def _exec(self, argv: list[str]) -> subprocess.CompletedProcess:
        # A timeout/missing-binary/etc is a SubprocessError or OSError, neither of which the AXP
        # execution path catches -- normalize everything here to the one error type it does.
        try: return self._run(argv,capture_output=True,text=True,timeout=10)
        except (subprocess.SubprocessError, OSError) as error: raise SecretBackendError(f"keychain command failed: {error}") from error

    def _find(self, account: str) -> bool:
        result=self._exec(["/usr/bin/security","find-generic-password","-s",self.service,"-a",account])
        return result.returncode==0

    def health(self, ref: CredentialReference) -> dict[str, Any]:
        available=self._find(ref.reference)
        return {"id":ref.id,"source":self.name,"available":available,"reference":ref.reference,"lifecycle":"active" if available else "unknown"}

    def reveal(self, ref: CredentialReference) -> str:
        result=self._exec(["/usr/bin/security","find-generic-password","-s",self.service,"-a",ref.reference,"-w"])
        if result.returncode!=0: raise SecretBackendError(f"credential {ref.id!r} was not found in the keychain")
        return result.stdout.strip()

    def set(self, ref: CredentialReference, value: str) -> dict[str, Any]:
        # NOTE: the macOS `security` CLI has no stdin-based input for generic passwords; the value is
        # necessarily passed as an argv element for the lifetime of this subprocess call.
        result=self._exec(["/usr/bin/security","add-generic-password","-s",self.service,"-a",ref.reference,"-w",value,"-U"])
        if result.returncode!=0: raise SecretBackendError(result.stderr.strip() or "keychain write failed")
        return {"id":ref.id,"source":self.name,"status":"updated"}


class OpenBaoBackend:
    """Optional adapter for a self-hosted OpenBao (or Vault-API-compatible) server. Off unless configured.

    Mutating calls are implemented but this milestone only exercises them against an injected fake
    transport in tests -- no real OpenBao mutation is performed during development/verification.
    """
    name="openbao"
    capabilities=frozenset({"get","health","reveal","rotate"})

    def __init__(self, base_url: str, token_env: str, mount: str = "secret", request: Callable[..., Any] | None = None):
        self.base_url=base_url.rstrip("/"); self.token_env=token_env; self.mount=mount
        self._request=request or self._http_request

    def _token(self) -> str:
        token=os.environ.get(self.token_env,"")
        if not token: raise SecretBackendError(f"OpenBao token environment variable {self.token_env!r} is not set")
        return token

    def _http_request(self, method: str, path: str, body: dict[str, Any] | None = None) -> dict[str, Any]:
        request=urllib.request.Request(f"{self.base_url}{path}",method=method,headers={"X-Vault-Token":self._token()},data=json.dumps(body).encode() if body is not None else None)
        try:
            with urllib.request.urlopen(request,timeout=10) as response: return json.loads(response.read() or b"{}")
        except urllib.error.URLError as error: raise SecretBackendError(f"OpenBao request failed: {error}") from error

    def status(self) -> dict[str, Any]: return self._request("GET","/v1/sys/health")

    def _path(self, ref: CredentialReference, kind: str) -> str: return f"/v1/{self.mount}/{kind}/{ref.reference}"

    def health(self, ref: CredentialReference) -> dict[str, Any]:
        try:
            metadata=self._request("GET",self._path(ref,"metadata"))
            versions=metadata.get("data",{}).get("versions",{})
            return {"id":ref.id,"source":self.name,"available":True,"reference":ref.reference,"version":metadata.get("data",{}).get("current_version"),"lifecycle":"active" if versions else "unknown"}
        except SecretBackendError as error:
            return {"id":ref.id,"source":self.name,"available":False,"reference":ref.reference,"error":str(error),"lifecycle":"unknown"}

    def reveal(self, ref: CredentialReference) -> str:
        data=self._request("GET",self._path(ref,"data"))
        value=data.get("data",{}).get("data",{}).get("value")
        if value is None: raise SecretBackendError(f"credential {ref.id!r} has no 'value' field at its OpenBao path")
        return value

    def set(self, ref: CredentialReference, value: str) -> dict[str, Any]:
        result=self._request("POST",self._path(ref,"data"),{"data":{"value":value}})
        return {"id":ref.id,"source":self.name,"status":"updated","version":result.get("data",{}).get("version")}

    def rotate_key(self) -> dict[str, Any]:
        """Rotate the backend's own Transit encryption key (not a provider credential)."""
        return self._request("POST",f"/v1/transit/keys/{self.mount}/rotate")


class SecretsManager:
    """Actor-facing secret operations (`secret.*` AXP actions) layered over CredentialRegistry + backends."""

    def __init__(self, registry: CredentialRegistry, backends: dict[str, SecretBackend] | None = None):
        self.registry=registry
        self.backends={"environment":EnvironmentBackend(), **(backends or {})}

    def _backend(self, ref: CredentialReference) -> SecretBackend:
        backend=self.backends.get(ref.source)
        if backend is None: raise SecretBackendError(f"credential {ref.id!r} uses unconfigured source {ref.source!r}")
        return backend

    def get(self, id: str) -> dict[str, Any]:
        ref=self.registry.get(id); health=self._backend(ref).health(ref)
        return {**health,"value":REDACTED}

    def set(self, id: str, value: str) -> dict[str, Any]:
        ref=self.registry.get(id); backend=self._backend(ref)
        if "set" not in backend.capabilities: raise SecretBackendError(f"the {backend.name!r} backend does not support secret.set")
        return backend.set(ref,value)

    def reveal(self, id: str) -> dict[str, Any]:
        """Returns the raw value. Reached only after the AXP execution path's policy check for the
        `secret.reveal` action. That check is a real gate only once you configure `[[roles]]` --
        an example role config should grant `secret.reveal` to human roles only, never `agent:*`;
        with no roles configured at all, policy is open and this returns the value to any caller,
        same as every other action (see PolicyEngine.enabled)."""
        ref=self.registry.get(id); backend=self._backend(ref)
        return {"id":id,"source":backend.name,"value":backend.reveal(ref)}

    def health(self, id: str) -> dict[str, Any]:
        ref=self.registry.get(id)
        return self._backend(ref).health(ref)

    def rotate(self, id: str, rotator: "ProviderRotator | None" = None) -> dict[str, Any]:
        self.registry.get(id)  # validates the credential id is actually configured
        if rotator is None:
            # No real provider rotator is wired in this milestone (see RotationWorkflow/MockRotator,
            # exercised directly in tests) -- never claim a rotation happened when none did.
            raise SecretBackendError(f"no rotation adapter is configured for credential {id!r}; secret.rotate is not yet implemented for a real backend")
        return RotationWorkflow(rotator).run()


class ProviderRotator(Protocol):
    """Provider-specific credential rotation, implemented by the owning provider plugin."""
    def create_candidate(self) -> Any: ...
    def verify_candidate(self, candidate: Any) -> bool: ...
    def activate(self, candidate: Any) -> None: ...
    def test(self) -> bool: ...
    def revoke_old(self, previous: Any) -> None: ...


class MockRotator:
    """Example/test rotator: in-memory only, never touches a real provider."""
    def __init__(self, should_verify: bool = True, should_pass_test: bool = True):
        self.current="initial"; self.should_verify=should_verify; self.should_pass_test=should_pass_test; self.revoked=[]

    def create_candidate(self) -> Any: return f"{self.current}-candidate"
    def verify_candidate(self, candidate: Any) -> bool: return self.should_verify
    def activate(self, candidate: Any) -> None: self._previous=self.current; self.current=candidate
    def test(self) -> bool: return self.should_pass_test
    def revoke_old(self, previous: Any) -> None: self.revoked.append(previous)


class RotationWorkflow:
    """CREATE -> VERIFY -> UPDATE(activate) -> TEST -> REVOKE -> REPORT. Verification/test failure keeps
    the old credential in place -- it is never revoked unless the new one is proven to work."""

    def __init__(self, rotator: ProviderRotator): self.rotator=rotator

    def run(self) -> dict[str, Any]:
        previous=getattr(self.rotator,"current",None)
        try:
            candidate=self.rotator.create_candidate()
        except Exception as error:
            return {"ok":False,"stage":"create","error":str(error)}
        if not self.rotator.verify_candidate(candidate):
            return {"ok":False,"stage":"verify","error":"candidate credential failed verification; old credential retained","retained":previous}
        self.rotator.activate(candidate)
        if not self.rotator.test():
            self.rotator.activate(previous)
            return {"ok":False,"stage":"test","error":"dependent connection test failed after activation; rolled back to previous credential","retained":previous}
        self.rotator.revoke_old(previous)
        return {"ok":True,"stage":"complete","previous":previous,"current":candidate}


ACTOR_CREDENTIAL_TYPES=("opaque_bearer","public_key","mtls","hardware","openpower_issued","local")
ACTOR_CREDENTIAL_STATES=("active","rotating","revoked","expired","disabled")


class ActorCredentialError(RuntimeError): pass


class ActorCredentialStore:
    """Credentials that authenticate a PRINCIPAL (an actor), distinct from the provider/resource
    secrets CredentialRegistry/SecretsManager already handle (Cloudflare tokens, DB passwords, ...).
    Storage mirrors GroupStore/StateStore/MissionStore: one JSON overlay, whole-file load/save.

    No raw secret material is ever accepted or stored here -- callers pass an already-computed
    `fingerprint` (e.g. a truncated sha256 of the value) and an optional `secret_ref` pointing at
    a CredentialReference id where the live value actually lives, resolved via SecretsManager.
    """

    def __init__(self, config_path):
        self.path=config_path.with_suffix(".actor_credentials.json")
        self._data=self._load()

    def _load(self) -> dict[str, Any]:
        if not self.path.exists(): return {"credentials":{}}
        try:
            data=json.loads(self.path.read_text(encoding="utf-8")); data.setdefault("credentials",{}); return data
        except (OSError,json.JSONDecodeError): return {"credentials":{}}

    def _save(self) -> None: self.path.write_text(json.dumps(self._data,indent=2)+"\n",encoding="utf-8")

    def _apply_expiry(self, record: dict[str,Any]) -> dict[str,Any]:
        if record["state"]=="active" and record["expires"]:
            try:
                if datetime.now(timezone.utc)>datetime.fromisoformat(record["expires"]): record["state"]="expired"
            except ValueError: pass
        return record

    def issue(self, principal: str, *, type: str="opaque_bearer", issuer: str="local", expires: str|None=None,
               fingerprint: str|None=None, secret_ref: str|None=None) -> dict[str,Any]:
        if type not in ACTOR_CREDENTIAL_TYPES: raise ActorCredentialError(f"invalid credential type {type!r}")
        record={"id":f"cred-{uuid4().hex[:8]}","principal":principal,"type":type,"issuer":issuer,
                "created":datetime.now(timezone.utc).isoformat(),"expires":expires,"last_used":None,
                "version":1,"state":"active","fingerprint":fingerprint,"secret_ref":secret_ref,"replaces":None}
        self._data["credentials"][record["id"]]=record; self._save()
        return record

    def inspect(self, credential_id: str) -> dict[str,Any]:
        try: record=self._data["credentials"][credential_id]
        except KeyError as error: raise ActorCredentialError(f"unknown credential {credential_id!r}") from error
        return self._apply_expiry(record)

    def list_for(self, principal: str|None=None) -> list[dict[str,Any]]:
        values=[self._apply_expiry(r) for r in self._data["credentials"].values()]
        return sorted([r for r in values if principal is None or r["principal"]==principal],key=lambda r:r["created"])

    def touch(self, credential_id: str) -> dict[str,Any]:
        record=self.inspect(credential_id); record["last_used"]=datetime.now(timezone.utc).isoformat(); self._save()
        return record

    def rotate(self, credential_id: str, *, fingerprint: str|None=None, secret_ref: str|None=None, expires: str|None=None) -> dict[str,Any]:
        previous=self.inspect(credential_id)
        if previous["state"]!="active": raise ActorCredentialError(f"credential {credential_id!r} is {previous['state']!r}, not active; cannot rotate")
        previous["state"]="rotating"
        current={"id":f"cred-{uuid4().hex[:8]}","principal":previous["principal"],"type":previous["type"],"issuer":previous["issuer"],
                 "created":datetime.now(timezone.utc).isoformat(),"expires":expires,"last_used":None,"version":previous["version"]+1,
                 "state":"active","fingerprint":fingerprint,"secret_ref":secret_ref,"replaces":credential_id}
        self._data["credentials"][current["id"]]=current; self._save()
        return {"previous":previous,"current":current}

    def confirm_rotation(self, previous_credential_id: str) -> dict[str,Any]:
        """The old credential is revoked only once the caller confirms the new one actually works."""
        previous=self.inspect(previous_credential_id)
        if previous["state"]!="rotating": raise ActorCredentialError(f"credential {previous_credential_id!r} is {previous['state']!r}, not rotating")
        previous["state"]="revoked"; self._save()
        return previous

    def revoke(self, credential_id: str) -> dict[str,Any]:
        record=self.inspect(credential_id); record["state"]="revoked"; self._save()
        return record
