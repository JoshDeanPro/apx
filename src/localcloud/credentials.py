"""Replaceable credential references. Resolved values never leave this module."""
from __future__ import annotations

import os
import re
from dataclasses import asdict, dataclass, field
from typing import Any

REDACTED="<redacted>"
SENSITIVE_KEYS=("token","secret","password","passwd","passphrase","api_key","apikey","private_key","client_secret","access_token","refresh_token","authorization","credential","cookie")


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

    def to_dict(self) -> dict[str,Any]:
        return {"id":self.id,"kind":self.kind,"source":self.source,"reference":self.reference,"scopes":self.scopes,"description":self.description,"metadata":self.metadata}


class CredentialRegistry:
    def __init__(self, references: dict[str,CredentialReference] | None = None): self.references=references or {}

    @classmethod
    def from_config(cls, values: dict[str,Any]) -> "CredentialRegistry":
        refs={}
        for name,value in values.items():
            refs[name]=CredentialReference(id=name,kind=value.get("kind",name),source=value.get("source","environment"),reference=value.get("reference",""),scopes=tuple(value.get("scopes",())),description=value.get("description",""),metadata={k:v for k,v in value.items() if k not in {"kind","source","reference","scopes","description"}})
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
            results.append({"id":reference.id,"kind":reference.kind,"configured":True,"available":available,"source":reference.source,"reference":reference.reference,"scopes":reference.scopes,"description":reference.description})
        return results

    def redact(self, value: Any) -> Any:
        known={os.environ.get(ref.reference) for ref in self.references.values() if ref.source=="environment" and os.environ.get(ref.reference)}
        def scrub(item: Any, key: str = "") -> Any:
            if isinstance(item,dict): return {k:(REDACTED if any(marker in k.lower() for marker in SENSITIVE_KEYS) else scrub(v,k)) for k,v in item.items()}
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
