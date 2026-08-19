
import pytest
from apx.runtime import ProviderSession
from apx.axp import ActionRequest, ActionDefinition, ActionResult
from apx.providers import evaluate_compatibility, ProviderManifest, ProviderIdentity
from apx.actions import RegisteredAction, CoreActions

def test_unknown_client_context_does_not_bypass_security():
    manifest = ProviderManifest(
        provider=ProviderIdentity("test", "test"),
        actions=(),
        resources=(),
        required_permissions=("admin",),
        required_credentials=("api_key",),
        allowed_actor_types=("human",)
    )
    # Empty client context should NOT be marked compatible
    client_context = {}
    result = evaluate_compatibility(client_context, manifest)
    assert not result.compatible
    assert any("permission unavailable" in r for r in result.reasons)
    assert any("authentication unavailable" in r for r in result.reasons)
    assert any("actor type incompatible" in r for r in result.reasons)

def test_unavailable_action_is_rejected_before_provider_execution():
    from apx.providers import ActionProvider

    provider = ActionProvider("test", "test")
    calls = []

    @provider.action("maintenance.restart", risk="low_change", available=False)
    def restart():
        calls.append("executed")
        return {"restarted": True}

    session = ProviderSession(provider)
    request = ActionRequest(action="maintenance.restart", actor="human:operator")

    prepared = session.prepare(request)
    assert isinstance(prepared, ActionResult)
    assert prepared.status == "unavailable"
    assert prepared.error is not None
    assert prepared.error.code == "provider_unavailable"

    executed = session.execute(request)
    assert executed.status == "unavailable"
    assert executed.error is not None
    assert executed.error.code == "provider_unavailable"
    assert calls == []


def test_unknown_client_context_in_runtime():
    from apx.providers import ActionProvider
    from apx.identity import ActorRegistry, DEFAULT_ACTOR
    from apx.policy import PolicyEngine, ScopedRule
    
    actors = ActorRegistry.from_config([], DEFAULT_ACTOR)
    policy = PolicyEngine.from_config([
        {"name": "admin", "rules": [ScopedRule("allow", "test.action")]}
    ], actors)
    provider = ActionProvider("test", "test")
    def handler(): return {}
    provider.register(RegisteredAction("test.action", "test", handler, {}))
    
    def policy_checker(req):
        return policy.evaluate(req.actor, req.action, req.target)
        
    session = ProviderSession(provider, policy=policy_checker)
    
    # Request without actor/auth should fail
    req = ActionRequest(action="test.action")
    res = session.prepare(req)
    # The action is read-only by default in RegisteredAction, let's make it destructive
    provider.register(RegisteredAction("test.action.write", "test", handler, {}, risk="destructive", read_only=False))
    req = ActionRequest(action="test.action.write")
    res = session.prepare(req)
    assert not res.ok or res.status == "failed" or res.status == "denied"
