# SPDX-License-Identifier: MPL-2.0
"""Local, user-owned Personal Context and privacy-preserving relevance matching."""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
import json
from pathlib import Path
from decimal import Decimal, InvalidOperation
from typing import Any
from uuid import uuid4

from .files import atomic_write


SENSITIVE_CATEGORIES=frozenset({"health","sexuality","religion","politics","financial_hardship","biometrics","precise_location"})
CONTENT_KINDS=("organic_recommendation","sponsored_recommendation","personalized_content","commercial_offer","user_requested_search")


@dataclass(frozen=True)
class ContextEntry:
    id: str; category: str; value: Any; source: str="user"; sensitive: bool=False
    expires_at: str|None=None; providers: tuple[str,...]=(); disclosure: str="local_only"
    confidence: float=1.0; created_at: str|None=None; updated_at: str|None=None
    last_used: str|None=None; user_verified: bool=True
    def __post_init__(self):
        if not 0 <= self.confidence <= 1: raise ValueError("confidence must be between 0 and 1")


@dataclass(frozen=True)
class PersonalizationPolicy:
    enabled: bool=True
    commercial_content: str="none"  # none, relevant_only, compensated_only
    allowed_categories: tuple[str,...]=()
    allowed_providers: tuple[str,...]=()
    minimum_compensation: dict[str,Any]|None=None
    sensitive_commercial: bool=False
    allowed_commercial_categories: tuple[str,...]=()
    blocked_commercial_categories: tuple[str,...]=()
    inference_enabled: bool=False


@dataclass(frozen=True)
class ContentVariant:
    id: str; labels: tuple[str,...]; content: Any; actions: tuple[str,...]=()


@dataclass(frozen=True)
class Offer:
    id: str; provider: str; title: str; categories: tuple[str,...]; description: str=""
    sponsored: bool=False; compensation: dict[str,Any]|None=None; actions: tuple[str,...]=()
    terms: dict[str,Any]=field(default_factory=dict)

    @property
    def kind(self): return "sponsored_recommendation" if self.sponsored else "organic_recommendation"


@dataclass(frozen=True)
class Campaign:
    id: str; provider: str; offers: tuple[Offer,...]; eligibility: dict[str,Any]=field(default_factory=dict)
    budget: dict[str,Any]=field(default_factory=dict); version: str="1.0"


@dataclass(frozen=True)
class Reward:
    id: str; provider: str; kind: str; value: dict[str,Any]; offer_id: str|None=None
    terms: dict[str,Any]=field(default_factory=dict); expires_at: str|None=None


@dataclass(frozen=True)
class Consent:
    subject: str; purposes: tuple[str,...]; providers: tuple[str,...]=(); categories: tuple[str,...]=()
    granted: bool=False; expires_at: str|None=None; version: str="1.0"


@dataclass(frozen=True)
class RelevanceRequest:
    provider: str; campaign_id: str; criteria: tuple[str,...]; purpose: str="content_selection"


@dataclass(frozen=True)
class RelevanceResult:
    campaign_id: str; eligible: bool; score: float=0; variant_id: str|None=None
    disclosed_claims: tuple[dict[str,Any],...]=()


@dataclass(frozen=True)
class RewardReceipt:
    receipt_id: str; reward_id: str; provider: str; status: str; value: dict[str,Any]
    timestamp: str; provider_reference: str|None=None


OPTIONAL_EXTENSIONS=frozenset({"personalization","content","offers","rewards","campaigns","commerce"})


@dataclass(frozen=True)
class OpaqueFinancialResource:
    id: str; kind: str; provider: str; label: str; capabilities: tuple[str,...]
    credential_reference: str|None=None
    def to_resource(self):
        from .axp import Resource
        if self.kind not in {"wallet","payment_method","financial_account"}: raise ValueError("invalid financial resource kind")
        return Resource(self.id,self.kind,self.label,{"provider":self.provider},capabilities=self.capabilities,tags=("opaque","financial"))


class PersonalContextStore:
    def __init__(self,path: str|Path,policy: PersonalizationPolicy|None=None):
        self.path=Path(path).expanduser(); self.policy=policy or PersonalizationPolicy(); self.entries: dict[str,ContextEntry]={}; self._load()
    def _load(self):
        if not self.path.exists(): return
        value=json.loads(self.path.read_text(encoding="utf-8")); self.policy=PersonalizationPolicy(**value.get("policy",{}))
        for item in value.get("entries",[]):
            for key in ("providers",): item[key]=tuple(item.get(key,()))
            entry=ContextEntry(**item); self.entries[entry.id]=entry
    def _save(self): atomic_write(self.path,json.dumps({"version":1,"policy":asdict(self.policy),"entries":[asdict(item) for item in self.entries.values()]},indent=2)+"\n")
    def add(self,category: str,value: Any,*,sensitive: bool|None=None,source="user",expires_at=None,providers=(),disclosure="local_only",confidence=1.0,user_verified=True):
        sensitive=category in SENSITIVE_CATEGORIES if sensitive is None else sensitive
        now=datetime.now(timezone.utc).isoformat(); entry=ContextEntry("ctx_"+uuid4().hex,category,value,source,sensitive,expires_at,tuple(providers),disclosure,confidence,now,now,None,user_verified); self.entries[entry.id]=entry; self._save(); return entry
    def update(self,entry_id: str,**changes):
        current=self.entries[entry_id]; allowed={"category","value","source","sensitive","expires_at","providers","disclosure","confidence","user_verified"}
        if set(changes)-allowed: raise ValueError("unsupported Personal Context field")
        values=asdict(current); values.update(changes); values["providers"]=tuple(values.get("providers",()))
        values["updated_at"]=datetime.now(timezone.utc).isoformat(); entry=ContextEntry(**values); self.entries[entry.id]=entry; self._save(); return entry
    def delete(self,entry_id): self.entries.pop(entry_id,None); self._save()
    def set_policy(self,policy: PersonalizationPolicy): self.policy=policy; self._save()
    def active(self):
        now=datetime.now(timezone.utc)
        return tuple(item for item in self.entries.values() if not item.expires_at or datetime.fromisoformat(item.expires_at.replace("Z","+00:00"))>now)
    def inspect(self): return {"path":str(self.path),"local":True,"policy":asdict(self.policy),"entries":[asdict(item) for item in self.active()]}

    def disclose(self,provider: str,categories: tuple[str,...]) -> dict[str,Any]:
        """Returns approved narrow claims, never raw values or context history."""
        if not self.policy.enabled or provider not in self.policy.allowed_providers: return {"provider":provider,"claims":[],"denied":True}
        claims=[]
        for entry in self.active():
            if entry.category not in categories or entry.category not in self.policy.allowed_categories: continue
            if entry.sensitive or entry.disclosure=="local_only": continue
            if entry.providers and provider not in entry.providers: continue
            claims.append({"category":entry.category,"matched":True})
        return {"provider":provider,"claims":claims,"denied":False}

    def _terms(self):
        values=set()
        for entry in self.active():
            if entry.sensitive: continue
            values.add(entry.category.lower())
            if isinstance(entry.value,str): values.update(entry.value.lower().split())
            elif isinstance(entry.value,(list,tuple)): values.update(str(item).lower() for item in entry.value)
        return values

    def select_variant(self,variants: tuple[ContentVariant,...]) -> dict[str,Any]|None:
        if not self.policy.enabled: return None
        terms=self._terms(); ranked=[(len(terms&set(item.labels)),index,item) for index,item in enumerate(variants)]
        if not ranked: return None
        score,_,item=max(ranked,key=lambda pair:(pair[0],pair[1])); return {"variant":item,"score":score,"disclosed":{}}

    def match_offer(self,offer: Offer) -> dict[str,Any]:
        if not self.policy.enabled: return {"relevant":False,"reason":"personalization disabled","label":"sponsored" if offer.sponsored else "organic"}
        if offer.sponsored:
            if self.policy.commercial_content=="none": return {"relevant":False,"reason":"sponsored content disabled","label":"sponsored"}
            if offer.provider not in self.policy.allowed_providers: return {"relevant":False,"reason":"provider not allowed","label":"sponsored"}
            if self.policy.commercial_content=="compensated_only" and not offer.compensation: return {"relevant":False,"reason":"compensation required","label":"sponsored"}
            minimum=self.policy.minimum_compensation
            if minimum:
                if not offer.compensation or offer.compensation.get("currency")!=minimum.get("currency"):
                    return {"relevant":False,"reason":"minimum compensation currency not met","label":"sponsored"}
                try: enough=Decimal(str(offer.compensation.get("amount")))>=Decimal(str(minimum.get("amount")))
                except (InvalidOperation,TypeError): enough=False
                if not enough: return {"relevant":False,"reason":"minimum compensation not met","label":"sponsored"}
            if set(offer.categories)&set(self.policy.blocked_commercial_categories): return {"relevant":False,"reason":"category blocked","label":"sponsored"}
            if self.policy.allowed_commercial_categories and not set(offer.categories)&set(self.policy.allowed_commercial_categories): return {"relevant":False,"reason":"category not allowed","label":"sponsored"}
        if any(category in SENSITIVE_CATEGORIES for category in offer.categories) and not self.policy.sensitive_commercial:
            return {"relevant":False,"reason":"sensitive commercial matching denied","label":"sponsored" if offer.sponsored else "organic"}
        score=len(self._terms()&{item.lower() for item in offer.categories})
        return {"relevant":score>0,"score":score,"label":"sponsored" if offer.sponsored else "organic","actions":list(offer.actions),"disclosed":{}}


def build_personal_provider(store: PersonalContextStore):
    """Local-only Actions for transparent content/attention decisions; no ad network."""
    from .providers import ActionProvider
    provider=ActionProvider("personal.local","APX Personal Context",provenance="local_component",metadata={"local_only":True})
    decisions={}
    schema={"type":"object","properties":{"content_id":{"type":"string"},"label":{"type":"string"}},"required":["content_id"],"additionalProperties":False}
    @provider.action("commercial_content.present",input_schema=schema,risk="read",confirmation="none",idempotent=True)
    def present(content_id,label="sponsored"):
        if store.policy.commercial_content=="none": return {"presented":False,"reason":"commercial content disabled"}
        decisions[content_id]="presented"; return {"presented":True,"content_id":content_id,"label":label}
    for action_id,status in (("commercial_content.accept","accepted"),("commercial_content.dismiss","dismissed")):
        def decide(content_id,label="sponsored",_status=status): decisions[content_id]=_status; return {"content_id":content_id,"status":_status,"label":label}
        provider.action(action_id,input_schema=schema,risk="low_change",confirmation="confirm",idempotent=True)(decide)
    reward_schema={"type":"object","properties":{"offer_id":{"type":"string"},"terms":{"type":"object"}},"required":["offer_id"],"additionalProperties":False}
    @provider.action("attention.reward.offer",input_schema=reward_schema,risk="read",confirmation="none",idempotent=True)
    def reward_offer(offer_id,terms=None): return {"offer_id":offer_id,"terms":terms or {},"claimed":False}
    @provider.action("attention.reward.claim",input_schema=reward_schema,risk="financial",confirmation="transaction",idempotent=True,retry="idempotency_required")
    def reward_claim(offer_id,terms=None): return {"offer_id":offer_id,"claim_requested":True,"terms":terms or {}}
    @provider.prepare("attention.reward.claim")
    def prepare_claim(offer_id,terms=None): return {"effect":"Claim an offered attention reward","confirmation_terms":{"offer_id":offer_id,"terms":terms or {}}}
    return provider
