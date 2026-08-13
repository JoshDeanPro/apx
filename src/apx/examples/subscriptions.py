"""In-memory reference provider used by documentation, demos, and conformance tests."""
from __future__ import annotations

from typing import Any

from ..actions import ActionError
from ..axp import Resource
from ..providers import ActionProvider

OBJECT={"type":"object","properties":{},"additionalProperties":False}


def build_reference_provider() -> ActionProvider:
    provider=ActionProvider("reference.local","Reference Subscriptions",provenance="local_component",
        profiles=("apx-commerce",),metadata={"example":True,"persistent":False})
    provider.resource(Resource("subscription:reference","subscription","Example Plan",{"currency":"USD"}))
    state={"active":False,"plan":None,"renewal":False,"access_until":None}

    @provider.action("subscription.inspect",description="Inspect the example subscription",input_schema=OBJECT,
        output_schema={"type":"object"},resource_type="subscription",risk="read",idempotent=True)
    def inspect() -> dict[str,Any]: return dict(state)

    purchase_schema={"type":"object","properties":{"plan":{"type":"string"}},"required":["plan"],"additionalProperties":False}
    @provider.action("subscription.start",description="Start the example monthly subscription",input_schema=purchase_schema,
        output_schema={"type":"object"},resource_type="subscription",risk="financial",confirmation="transaction",
        permissions=("subscription.start",),reversible=True,reverse_action="subscription.cancel",idempotent=False,
        side_effects=("creates recurring monthly charge",),tags=("commerce","subscription"))
    def start(plan: str) -> dict[str,Any]:
        state.update(active=True,plan=plan,renewal=True,access_until=None); return dict(state)

    @provider.prepare("subscription.start")
    def prepare_start(plan: str) -> dict[str,Any]:
        terms={"amount":"9.99","currency":"USD","merchant":"Reference Subscriptions","item":plan,
            "recurring":{"frequency":"monthly","renews":True},"cancellation_action":"subscription.cancel"}
        return {"effect":f"Start {plan}","cost":{"amount":"9.99","currency":"USD"},"recurring_terms":terms["recurring"],"confirmation_terms":terms}

    @provider.action("subscription.cancel",description="Cancel renewal while retaining current access",input_schema=OBJECT,
        output_schema={"type":"object"},resource_type="subscription",risk="account_change",confirmation="confirm",
        permissions=("subscription.cancel",),reversible=True,reverse_action="subscription.resume",idempotent=True,
        side_effects=("disables renewal",),expected_verification="renewal is false",tags=("commerce","subscription"))
    def cancel() -> dict[str,Any]:
        if not state["active"]: raise ActionError("subscription is not active")
        state["renewal"]=False; return dict(state)

    @provider.prepare("subscription.cancel")
    def prepare_cancel() -> dict[str,Any]: return {"effect":"Disable subscription renewal; current access is retained"}

    @provider.verify("subscription.cancel")
    def verify_cancel(result: dict[str,Any]) -> bool: return result["renewal"] is False

    @provider.action("subscription.resume",description="Resume renewal",input_schema=OBJECT,output_schema={"type":"object"},
        resource_type="subscription",risk="account_change",confirmation="confirm",permissions=("subscription.resume",),
        reversible=True,reverse_action="subscription.cancel",idempotent=True,side_effects=("enables renewal",),tags=("commerce","subscription"))
    def resume() -> dict[str,Any]: state.update(active=True,renewal=True); return dict(state)

    @provider.verify("subscription.resume")
    def verify_resume(result: dict[str,Any]) -> bool: return result["renewal"] is True

    return provider


if __name__=="__main__":
    import json
    print(json.dumps(build_reference_provider().manifest().to_dict(),indent=2))
