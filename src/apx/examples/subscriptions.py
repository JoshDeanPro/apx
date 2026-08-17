# SPDX-License-Identifier: MIT
"""In-memory reference provider used by documentation, demos, and conformance tests."""
from __future__ import annotations

from typing import Any

from ..actions import ActionError
from ..axp import Resource
from ..providers import ActionProvider
from ..runtime import ProviderPolicyDenied

OBJECT={"type":"object","properties":{},"additionalProperties":False}


def build_reference_provider() -> ActionProvider:
    provider=ActionProvider("reference.local","Reference Subscriptions",provenance="local_component",
        profiles=("apx-commerce",),metadata={"example":True,"persistent":False})
    provider.resource(Resource("subscription:reference","subscription","Example Plan",{"currency":"USD"}))
    state={"active":False,"plan":None,"renewal":False,"access_until":None,"version":0,"cancellations":0}

    @provider.action("subscription.inspect",description="Inspect the example subscription",input_schema=OBJECT,
        output_schema={"type":"object"},resource_type="subscription",risk="read",idempotent=True)
    def inspect() -> dict[str,Any]: return dict(state)

    purchase_schema={"type":"object","properties":{"plan":{"type":"string"}},"required":["plan"],"additionalProperties":False}
    @provider.action("subscription.start",description="Start the example monthly subscription",input_schema=purchase_schema,
        output_schema={"type":"object"},resource_type="subscription",risk="financial",confirmation="transaction",
        permissions=("subscription.start",),reversible=True,reverse_action="subscription.cancel",idempotent=False,
        side_effects=("creates recurring monthly charge",),tags=("commerce","subscription"))
    def start(plan: str) -> dict[str,Any]:
        state.update(active=True,plan=plan,renewal=True,access_until=None,version=state["version"]+1); return dict(state)

    @provider.prepare("subscription.start")
    def prepare_start(plan: str) -> dict[str,Any]:
        terms={"amount":"9.99","currency":"USD","merchant":"Reference Subscriptions","item":plan,
            "recurring":{"frequency":"monthly","renews":True},"cancellation_action":"subscription.cancel"}
        return {"effect":f"Start {plan}","cost":{"amount":"9.99","currency":"USD"},"recurring_terms":terms["recurring"],"confirmation_terms":terms,
            "authoritative_state_version":str(state["version"]),"authoritative_state":{"active":state["active"],"renewal":state["renewal"]}}

    @provider.action("subscription.cancel",description="Cancel renewal while retaining current access",input_schema=OBJECT,
        output_schema={"type":"object"},resource_type="subscription",risk="account_change",confirmation="confirm",
        permissions=("subscription.cancel",),reversible=True,reverse_action="subscription.resume",idempotent=True,
        side_effects=("disables renewal",),expected_verification="renewal is false",tags=("commerce","subscription"),
        retry="idempotency_required",preconditions=({"path":"renewal","equals":True},),postconditions=({"path":"renewal","equals":False},),
        constraints={"max_concurrent_per_resource":1,"cooldown_seconds":1})
    def cancel() -> dict[str,Any]:
        if not state["active"]: raise ActionError("subscription is not active")
        state["renewal"]=False; state["version"]+=1; state["cancellations"]+=1; return dict(state)

    @provider.prepare("subscription.cancel")
    def prepare_cancel() -> dict[str,Any]: return {"effect":"Disable subscription renewal; current access is retained",
        "authoritative_state_version":str(state["version"]),"authoritative_state":{"active":state["active"],"renewal":state["renewal"]}}

    @provider.verify("subscription.cancel")
    def verify_cancel(result: dict[str,Any]) -> bool: return result["renewal"] is False

    @provider.action("subscription.resume",description="Resume renewal",input_schema=OBJECT,output_schema={"type":"object"},
        resource_type="subscription",risk="account_change",confirmation="confirm",permissions=("subscription.resume",),
        reversible=True,reverse_action="subscription.cancel",idempotent=True,side_effects=("enables renewal",),tags=("commerce","subscription"))
    def resume() -> dict[str,Any]: state.update(active=True,renewal=True,version=state["version"]+1); return dict(state)

    @provider.verify("subscription.resume")
    def verify_resume(result: dict[str,Any]) -> bool: return result["renewal"] is True

    refund_schema={"type":"object","properties":{"order_id":{"type":"string"}},"required":["order_id"],"additionalProperties":False}
    @provider.action("order.refund.request",description="Request a refund under provider policy",input_schema=refund_schema,
        output_schema={"type":"object"},resource_type="order",risk="financial",confirmation="transaction",
        permissions=("order.refund.request",),idempotent=True,retry="idempotency_required",tags=("commerce",))
    def refund(order_id: str) -> dict[str,Any]:
        raise ProviderPolicyDenied("outside eligibility window",provider_code="refund_window_closed",next_actions=("support.case.create",))

    @provider.prepare("order.refund.request")
    def prepare_refund(order_id: str) -> dict[str,Any]:
        terms={"order_id":order_id,"amount":"9.99","currency":"USD"}
        return {"effect":f"Request refund for {order_id}","confirmation_terms":terms,"resolved_terms":terms,
            "authoritative_state_version":"order-v1","authoritative_state":{"eligible":False}}

    @provider.action("account.sessions.revoke",description="Revoke account sessions",input_schema=OBJECT,
        output_schema={"type":"object"},resource_type="account",risk="security_critical",confirmation="security_critical",
        permissions=("account.sessions.revoke",),idempotent=True,retry="idempotency_required")
    def revoke_sessions() -> dict[str,Any]: return {"revoked":True,"active_sessions":0}

    @provider.prepare("account.sessions.revoke")
    def prepare_revoke_sessions() -> dict[str,Any]:
        return {"effect":"Revoke every active account session","authoritative_state_version":"sessions-v1",
            "authoritative_state":{"scope":"all active sessions"}}

    return provider


if __name__=="__main__":
    import json
    print(json.dumps(build_reference_provider().manifest().to_dict(),indent=2))
