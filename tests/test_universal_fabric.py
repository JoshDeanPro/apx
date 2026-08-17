import json
import tempfile
import unittest
from pathlib import Path

from apx import (APXClient, ActionComponent, ActionProvider, Capability, CapabilityGraph, ComponentCandidate,
    CompositionEngine, CompositionStep, ContentVariant, LocalClientTransport, Offer,
    PersonalContextStore, PersonalizationPolicy, ProviderSession, Resource, audit_component_candidate)
from apx import OpaqueFinancialResource
from apx import build_personal_provider
from apx.providers import validate_provider
from apx.actions import ActionRegistry, RegisteredAction
from apx.bridges.browser import BrowserBridge
from apx.bridges.home_assistant import HomeAssistantBridge
from apx.examples.subscriptions import build_reference_provider
from apx.http import HTTPResult
from apx.software import discover_local_software
from apx.conformance import bridge_conformance


class FakeBrowser:
    def __init__(self): self.url=None; self.fields={}; self.state_calls=0
    def open(self,url): self.url=url; return {"url":url,"title":"Example"}
    def structured_state(self): self.state_calls+=1; return {"url":self.url,"elements":[{"ref":"e0","role":"textbox","name":"email"}]}
    def click(self,reference): return {"clicked":reference}
    def fill(self,fields): self.fields.update(fields); return {"filled":sorted(fields)}
    def close(self): pass


class FakeHomeAssistantHTTP:
    def __init__(self): self.state="off"; self.authorization=[]
    def request(self,method,url,headers=None,json=None,**kwargs):
        self.authorization.append(headers.get("Authorization"))
        if url.endswith("/api/states"): value=[{"entity_id":"light.study","state":self.state,"attributes":{"friendly_name":"Study"}}]
        elif "/api/services/light/turn_on" in url: self.state="on"; value=[]
        elif url.endswith("/api/states/light.study"): value={"entity_id":"light.study","state":self.state,"attributes":{}}
        else: value={}
        return HTTPResult(200,{},__import__("json").dumps(value).encode())


class CapabilityGraphTests(unittest.TestCase):
    def test_intent_capability_action_and_native_first_fallback(self):
        graph=CapabilityGraph(); graph.add_resource(Resource("service:native","subscription","Native")); graph.add_resource(Resource("service:web","subscription","Web"))
        action=RegisteredAction("subscription.cancel","Cancel renewal",lambda:{}, {"type":"object"},False,False,risk="account_change",confirmation="confirm",provider="provider")
        graph.add_action(action.definition())
        graph.add_capability(Capability("subscription","service:native",actions=("subscription.cancel",),provenance="native_apx",reliability=.99))
        graph.add_capability(Capability("subscription","service:web",actions=("subscription.cancel",),provenance="browser_component",reliability=.8))
        self.assertEqual(graph.paths("subscription.cancel")[0].resource,"service:native")
        self.assertEqual(len(graph.paths("subscription.cancel",resource="service:web",allow_fallback=True)),0)
        fallback=graph.paths("subscription.cancel",resource="service:web",allow_fallback=True,confirmed_lower_trust=True)
        self.assertEqual(fallback[0].provenance,"browser_component")

    def test_search_and_alternative(self):
        graph=CapabilityGraph(); graph.add_resource(Resource("machine:gpu","machine","Workstation",tags=("gpu",)))
        graph.add_capability(Capability("compute.gpu","machine:gpu","GPU compute",actions=("compute.inspect",)))
        self.assertEqual(graph.search("compute gpu")["capabilities"][0]["id"],"compute.gpu")


class BridgeProofTests(unittest.TestCase):
    def test_browser_structured_form_fill_uses_no_reasoning_loop(self):
        driver=FakeBrowser(); bridge=BrowserBridge(driver); registry=ActionRegistry(); bridge.register_actions(registry)
        registry.get("browser.open").handler("https://example.test")
        first=registry.get("browser.inspect").handler(); second=registry.get("browser.inspect").handler()
        registry.get("form.fill").handler({"email":"person@example.test"})
        self.assertFalse(first["cached"]); self.assertTrue(second["cached"]); self.assertEqual(driver.fields["email"],"person@example.test")
        self.assertEqual(bridge.metrics.reasoning_calls,0); self.assertEqual(bridge.metrics.tool_calls,3); self.assertEqual(driver.state_calls,1)

    def test_home_assistant_light_bridge_discovers_mutates_and_verifies(self):
        http=FakeHomeAssistantHTTP(); bridge=HomeAssistantBridge("http://127.0.0.1:8123",lambda:"opaque-token",client=http)
        resources=bridge.discover_resources(); capabilities=bridge.discover_capabilities(); registry=ActionRegistry(); bridge.register_actions(registry)
        result=registry.get("light.turn_on").handler("light.study")
        self.assertEqual(resources[0].kind,"light"); self.assertIn("light.turn_on",capabilities[0].actions)
        self.assertEqual(result["after"],"on"); self.assertTrue(result["verified"])
        self.assertTrue(all(value=="Bearer opaque-token" for value in http.authorization))
        self.assertNotIn("opaque-token",json.dumps([item.to_dict() for item in resources]))
        self.assertTrue(registry.get("light.turn_on").handler("light.study")["verified"])

    def test_bridges_pass_generic_conformance(self):
        self.assertEqual(bridge_conformance(BrowserBridge(FakeBrowser())),[])
        self.assertEqual(bridge_conformance(HomeAssistantBridge("http://127.0.0.1:8123",lambda:"token",client=FakeHomeAssistantHTTP())),[])

    def test_local_software_is_discovered_not_installed(self):
        resources,capabilities=discover_local_software(application_limit=3)
        self.assertTrue(any(item.id=="software:git" for item in resources)); self.assertTrue(capabilities)


class PersonalPrivacyTests(unittest.TestCase):
    def setUp(self): self.temp=tempfile.TemporaryDirectory(); self.path=Path(self.temp.name)/"personal.json"
    def tearDown(self): self.temp.cleanup()
    def test_local_variant_selection_discloses_nothing(self):
        store=PersonalContextStore(self.path); store.add("technology","technical developer")
        selected=store.select_variant((ContentVariant("general",("general",),"General"),ContentVariant("technical",("technical","developer"),"Technical")))
        self.assertEqual(selected["variant"].id,"technical"); self.assertEqual(selected["disclosed"],{})
        self.assertEqual(self.path.stat().st_mode & 0o777,0o600)
    def test_personal_context_firewall_and_sensitive_default_deny(self):
        policy=PersonalizationPolicy(commercial_content="relevant_only",allowed_categories=("technology",),allowed_providers=("business.example",))
        store=PersonalContextStore(self.path,policy); store.add("technology","gpu",disclosure="claim",providers=("business.example",)); store.add("health","private")
        disclosure=store.disclose("business.example",("technology","health"))
        self.assertEqual(disclosure["claims"],[{"category":"technology","matched":True}]); self.assertNotIn("gpu",json.dumps(disclosure)); self.assertNotIn("private",json.dumps(disclosure))
        offer=Offer("offer-1","business.example","Health offer",("health",),sponsored=True)
        self.assertFalse(store.match_offer(offer)["relevant"])
    def test_sponsored_is_labeled_and_cannot_override_organic(self):
        policy=PersonalizationPolicy(commercial_content="relevant_only",allowed_providers=("business.example",))
        store=PersonalContextStore(self.path,policy); store.add("technology","gpu")
        sponsored=store.match_offer(Offer("s","business.example","GPU ad",("gpu",),sponsored=True,actions=("instance.quote",)))
        organic=store.match_offer(Offer("o","community","GPU option",("gpu",),sponsored=False))
        self.assertEqual(sponsored["label"],"sponsored"); self.assertEqual(organic["label"],"organic")
    def test_wallet_is_opaque_and_never_serializes_credential_reference(self):
        wallet=OpaqueFinancialResource("wallet:test","wallet","provider.example","Personal Wallet",("payment.prepare","payment.send"),"keychain:wallet")
        encoded=json.dumps(wallet.to_resource().to_dict())
        self.assertNotIn("keychain:wallet",encoded); self.assertIn("payment.send",encoded)
    def test_disabled_policy_stops_matching_and_context_is_editable(self):
        store=PersonalContextStore(self.path,PersonalizationPolicy(enabled=False)); entry=store.add("technology","developer")
        store.update(entry.id,value="general"); self.assertEqual(store.inspect()["entries"][0]["value"],"general")
        self.assertIsNone(store.select_variant((ContentVariant("technical",("developer",),"Technical"),)))
        self.assertFalse(store.match_offer(Offer("o","provider","Offer",("general",)))["relevant"])
    def test_personal_content_actions_are_real_and_conformant(self):
        store=PersonalContextStore(self.path,PersonalizationPolicy(commercial_content="none")); provider=build_personal_provider(store)
        self.assertEqual(validate_provider(provider),[])
        client=APXClient(LocalClientTransport(ProviderSession(provider)), client_context={"permissions": ["subscription.start", "subscription.inspect", "subscription.cancel", "subscription.resume", "account.sessions.revoke", "order.refund.request"], "authentication": ["session"], "actor_type": "human"})
        result=client.execute("commercial_content.present",input={"content_id":"offer-1"})
        self.assertFalse(result.result["presented"])


class ComponentTests(unittest.TestCase):
    def test_missing_capability_becomes_validated_reusable_component(self):
        calls=[]; component=ActionComponent("text.normalize","1.0",(CompositionStep("text.lower",bind={"value":"text"}),),tests_passed=True,approved=True)
        result=CompositionEngine(lambda action,inputs:calls.append((action,inputs)) or inputs["value"].lower()).run(component,{"text":"HELLO"})
        self.assertEqual(result["results"],["hello"]); self.assertEqual(result["reasoning_calls"],0)
    def test_unapproved_generated_component_fails_closed(self):
        with self.assertRaises(ValueError): ActionComponent("unsafe","1",(),tests_passed=True,approved=False)
    def test_open_source_candidate_audit_rejects_abandoned_or_unknown_license(self):
        result=audit_component_candidate(ComponentCandidate("old","https://github.com/example/old","unknown",False))
        self.assertFalse(result["approved"]); self.assertIn("license requires review",result["problems"])


class ProviderSameModelTests(unittest.TestCase):
    def test_reference_provider_remains_normal_apx_provider(self):
        provider=build_reference_provider(); client=APXClient(LocalClientTransport(ProviderSession(provider)), client_context={"permissions": ["subscription.start", "subscription.inspect", "subscription.cancel", "subscription.resume", "account.sessions.revoke", "order.refund.request"], "authentication": ["session"], "actor_type": "human"})
        self.assertIn("subscription.inspect",{item.id for item in client.actions()}); self.assertTrue(client.execute("subscription.inspect").ok)


if __name__=="__main__": unittest.main()
