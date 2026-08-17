import json
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from apx import APX, ActionProvider, ActionRequest, CredentialHandle, HTTPProviderAdapter, ProviderManifest
from apx.examples.subscriptions import build_reference_provider
from apx.providers import DISCOVERY_PATH, validate_provider


def config(root: Path, policy: bool = False) -> Path:
    path=root/"apx.toml"
    text='version=1\n[[hosts]]\nname="test"\ntransport="local"\n'
    if policy:
        text+='''
[[actors]]
id="agent:test"
kind="agent"
roles=["reader"]
[[roles]]
name="reader"
allow=[{action="subscription.inspect"}]
deny=[{action="subscription.cancel"}]
'''
    path.write_text(text)
    return path


class ProviderSchemaTests(unittest.TestCase):
    def test_manifest_round_trip_and_conformance(self):
        provider=build_reference_provider(); manifest=provider.manifest()
        decoded=ProviderManifest.from_dict(json.loads(json.dumps(manifest.to_dict())))
        self.assertEqual(decoded.provider.id,"reference.local")
        self.assertEqual(validate_provider(provider),[])
        self.assertEqual({a.risk for a in decoded.actions},{"read","financial","account_change","security_critical"})
        self.assertNotIn("secret",json.dumps(manifest.to_dict()).lower())

    def test_commerce_reciprocity_and_reversal_conformance(self):
        provider=ActionProvider("bad.local","Bad",profiles=("apx-commerce",))
        @provider.action("subscription.start",risk="financial",confirmation="transaction")
        def start(): return {}
        self.assertTrue(any("subscription.cancel" in error for error in validate_provider(provider)))

    def test_generated_component_is_descriptive_and_scoped(self):
        provider=ActionProvider("generated.horoscope","Generated",provenance="generated_component")
        @provider.action("horoscope.fetch",permissions=("network:horoscope.example",),tags=("generated",))
        def fetch(): return {"sign":"Aries"}
        definition=provider.actions[0].definition()
        self.assertEqual(definition.provenance,"generated_component")
        self.assertEqual(definition.requirements.permissions,("network:horoscope.example",))


class ProviderLifecycleTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(); self.cloud=APX(config(Path(self.temp.name)),plugins=False)
        self.provider=build_reference_provider(); self.cloud.register_provider(self.provider)
        self.auth={"principal_id":"agent:test","authentication_method":"test","issuer":"test"}

    def tearDown(self): self.temp.cleanup()

    def confirm(self, level, nonce, terms=None, expires=None):
        value={"level":level,"confirmed":True,"authorization_id":nonce,"expires_at":expires or (datetime.now(timezone.utc)+timedelta(minutes=5)).isoformat()}
        if terms is not None: value["terms"]=terms
        return value

    def test_real_prepare_execute_verify_receipt_and_reverse(self):
        prepared_purchase=self.cloud.prepare("subscription.start",plan="Example Plus")
        denied=self.cloud.run("subscription.start",actor="agent:test",auth_context=self.auth,plan="Example Plus",confirmation=self.confirm("transaction","purchase-1",{"wrong":True}))
        self.assertEqual(denied.status,"awaiting-approval")
        started=self.cloud.run("subscription.start",actor="agent:test",auth_context=self.auth,plan="Example Plus",confirmation=self.confirm("transaction","purchase-2",prepared_purchase.confirmation_terms))
        self.assertTrue(started.ok); self.assertTrue(started.receipt.reversible)
        self.assertTrue(self.cloud.run("subscription.inspect",actor="agent:test").result["renewal"])
        prepared=self.cloud.prepare("subscription.cancel",actor="agent:test")
        self.assertEqual(prepared.confirmation_required,"confirm")
        blocked=self.cloud.run("subscription.cancel",actor="agent:test",auth_context=self.auth)
        self.assertEqual(blocked.status,"awaiting-approval")
        cancelled=self.cloud.run("subscription.cancel",actor="agent:test",auth_context=self.auth,confirmation=self.confirm("confirm","cancel-1"))
        self.assertFalse(cancelled.result["renewal"]); self.assertEqual(cancelled.receipt.verification_status,"verified")
        self.assertEqual(cancelled.receipt.reverse_action,"subscription.resume")
        resumed=self.cloud.run("subscription.resume",actor="agent:test",auth_context=self.auth,confirmation=self.confirm("confirm","resume-1"))
        self.assertTrue(resumed.result["renewal"]); self.assertEqual(resumed.receipt.verification_status,"verified")
        names=[event.name for event in self.cloud.events.history]
        self.assertIn("action.prepared",names); self.assertIn("action.awaiting_approval",names); self.assertIn("action.completed",names)

    def test_auth_expiry_replay_and_revocation(self):
        unauth=self.cloud.run("subscription.cancel",actor="agent:test",confirmation=self.confirm("confirm","x"))
        self.assertEqual(unauth.error.code,"authentication_required")
        expired=(datetime.now(timezone.utc)-timedelta(seconds=1)).isoformat()
        outcome=self.cloud.run("subscription.cancel",actor="agent:test",auth_context=self.auth,confirmation=self.confirm("confirm","expired",expires=expired))
        self.assertEqual(outcome.status,"awaiting-approval")
        first=self.cloud.run("subscription.resume",actor="agent:test",auth_context=self.auth,confirmation=self.confirm("confirm","once"))
        replay=self.cloud.run("subscription.resume",actor="agent:test",auth_context=self.auth,confirmation=self.confirm("confirm","once"))
        self.assertTrue(first.ok); self.assertEqual(replay.status,"awaiting-approval")
        revoked=CredentialHandle("cred","proof_of_possession","issuer","reference.local",fingerprint="sha256:public",revoked=True)
        result=self.cloud.execute(ActionRequest("subscription.cancel",actor="agent:test",auth_context=self.auth,credential=revoked,confirmation=self.confirm("confirm","new")))
        self.assertEqual(result.error.code,"credential_revoked")

    def test_minimum_disclosure_actor(self):
        request=ActionRequest("subscription.inspect",actor="agent:test",delegated_by="human:owner",client="OpenPower",device="machine:mac",auth_context={"conversation":"must not leak"})
        value=self.cloud.provider_actor(request).to_dict()
        encoded=json.dumps(value)
        self.assertIn("agent:test",encoded); self.assertIn("human:owner",encoded)
        self.assertNotIn("conversation",encoded); self.assertNotIn("profile",encoded)

    def test_receipt_and_events_redact_secret_outputs(self):
        provider=ActionProvider("security.local","Security",provenance="local_component")
        @provider.action("account.password.rotate",risk="security_critical",confirmation="security_critical",idempotent=False,input_schema={"type":"object","properties":{"secret_ref":{"type":"string","x-apx-secret":True}},"required":["secret_ref"]})
        def rotate(secret_ref): return {"password":"never-return-this","credential_ref":secret_ref,"rotated":True}
        self.cloud.register_provider(provider)
        result=self.cloud.run("account.password.rotate",actor="agent:test",auth_context=self.auth,secret_ref="vault:item",confirmation=self.confirm("security_critical","rotate-1"))
        self.assertEqual(result.result["password"],"<redacted>")
        self.assertNotIn("never-return-this",json.dumps(result.receipt.to_dict()))
        self.assertNotIn("vault:item",json.dumps([e.to_dict() for e in self.cloud.events.history]))


class ProviderPolicyAndHTTPTests(unittest.TestCase):
    def test_explicit_deny_wins_for_provider_action(self):
        with tempfile.TemporaryDirectory() as directory:
            cloud=APX(config(Path(directory),policy=True),plugins=False); cloud.register_provider(build_reference_provider())
            self.assertTrue(cloud.run("subscription.inspect",actor="agent:test").ok)
            denied=cloud.run("subscription.cancel",actor="agent:test",auth_context={"principal_id":"agent:test"},confirmation={"level":"confirm","confirmed":True})
            self.assertEqual(denied.error.code,"permission_denied")

    def test_http_adapter_manifest_lifecycle_and_receipt(self):
        with tempfile.TemporaryDirectory() as directory:
            cloud=APX(config(Path(directory)),plugins=False); provider=build_reference_provider(); cloud.register_provider(provider)
            adapter=HTTPProviderAdapter(provider,cloud.execute,cloud.prepare)
            status,headers,manifest=adapter.handle("GET",DISCOVERY_PATH)
            self.assertEqual(status,200); self.assertEqual(manifest["provider"]["id"],"reference.local")
            request=ActionRequest("subscription.resume",actor="agent:test",auth_context={"principal_id":"agent:test"},confirmation={"level":"confirm","confirmed":True,"authorization_id":"http-1"})
            status,_,result=adapter.handle("POST","/apx/actions/execute",request.to_dict())
            self.assertEqual(status,200); receipt_id=result["receipt"]["receipt_id"]
            self.assertEqual(adapter.handle("GET",f"/apx/receipts/{receipt_id}")[2]["status"],"completed")


if __name__ == "__main__": unittest.main()
