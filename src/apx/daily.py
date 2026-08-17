# SPDX-License-Identifier: MIT
"""Domain-neutral daily-life capability contracts; implementations remain Providers."""
from __future__ import annotations
from dataclasses import dataclass
from typing import Protocol

from .axp import Resource


class PasswordManager(Protocol):
    id: str
    def generate_reference(self,policy: dict) -> str: ...
    def deliver(self,credential_reference: str,provider_reference: str) -> None: ...


@dataclass(frozen=True)
class PasswordManagerResource:
    id: str; provider: str; label: str; capabilities: tuple[str,...]=("credential.generate","credential.save","credential.rotate","credential.sync")
    def to_resource(self): return Resource(self.id,"password_manager",self.label,{"provider":self.provider},capabilities=self.capabilities,tags=("secret_pathway","opaque"))


@dataclass(frozen=True)
class CalendarResource:
    id: str; provider: str; label: str; capabilities: tuple[str,...]=("calendar.event.list","calendar.event.create","calendar.event.update","calendar.event.cancel","reminder.create","reminder.complete")
    def to_resource(self): return Resource(self.id,"calendar",self.label,{"provider":self.provider},capabilities=self.capabilities)


@dataclass(frozen=True)
class SubscriptionObservation:
    id: str; merchant: str; amount: dict; cadence: str|None=None; provider_resource: str|None=None
    confidence: float=0; source: str="financial_provider"
    def __post_init__(self):
        if not 0 <= self.confidence <= 1: raise ValueError("confidence must be between 0 and 1")


@dataclass(frozen=True)
class FinancialResource:
    id: str; kind: str; provider: str; label: str
    capabilities: tuple[str,...]=("transaction.inspect","subscription.detect","merchant.inspect","recurring_payment.inspect")
    credential_reference: str|None=None
    def to_resource(self):
        if self.kind not in {"bank_account","credit_account","wallet","payment_service"}: raise ValueError("invalid financial resource")
        return Resource(self.id,self.kind,self.label,{"provider":self.provider},capabilities=self.capabilities,tags=("opaque","financial"))


def relate_subscription(observation: SubscriptionObservation,provider_resources: tuple[Resource,...]) -> dict:
    """Relate an observation only when an explicit provider Resource matches; never invent eligibility."""
    match=next((item for item in provider_resources if item.id==observation.provider_resource),None)
    return {"observation":observation.id,"provider_resource":match.id if match else None,"actions":list(match.capabilities) if match else [],"authoritative":False}
