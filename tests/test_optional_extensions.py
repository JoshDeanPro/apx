import json,tempfile,unittest
from pathlib import Path

from apx import APXClient,CalendarResource,FinancialResource,LocalClientTransport,PasswordManagerResource,ProviderSession,SubscriptionObservation,relate_subscription
from apx.conformance import provider_conformance
from apx.examples.commercial import build_commercial_reference_provider


class OptionalExtensionTests(unittest.TestCase):
    def test_provider_can_disable_every_commercial_extension(self):
        provider=build_commercial_reference_provider(enabled=False)
        self.assertEqual(provider.manifest().extensions,{})
        self.assertEqual(provider.actions,())
        self.assertEqual(provider_conformance(provider),[])

    def test_enabled_extensions_are_advertised_and_conform(self):
        provider=build_commercial_reference_provider()
        self.assertEqual(set(provider.manifest().extensions),{"content","offers","rewards","campaigns"})
        self.assertEqual(provider_conformance(provider),[])

    def test_reward_requires_acceptance_and_bound_transaction_confirmation(self):
        client=APXClient(LocalClientTransport(ProviderSession(build_commercial_reference_provider())))
        accepted=client.prepare("offer.accept",input={"offer_id":"gpu-test"},actor="human:test")
        self.assertEqual(client.authorize(accepted.prepared_action_id,{"confirmed":True,"level":"confirm","authorization_id":"accept-1"}).status,"authorized")
        self.assertTrue(client.execute("offer.accept",input={"offer_id":"gpu-test"},actor="human:test",prepared_action_id=accepted.prepared_action_id,idempotency_key="accept").ok)
        claim=client.prepare("reward.claim",input={"reward_id":"reward-test"},actor="human:test")
        rejected=client.authorize(claim.prepared_action_id,{"confirmed":True,"level":"transaction","authorization_id":"bad","terms":{"wrong":True}})
        self.assertEqual(rejected.status,"authorization_required")
        self.assertEqual(client.authorize(claim.prepared_action_id,{"confirmed":True,"level":"transaction","authorization_id":"claim-1","terms":claim.confirmation_terms}).status,"authorized")
        result=client.execute("reward.claim",input={"reward_id":"reward-test"},actor="human:test",prepared_action_id=claim.prepared_action_id,idempotency_key="claim")
        self.assertTrue(result.ok); self.assertEqual(result.result["status"],"completed"); self.assertEqual(result.result["value"]["currency"],"TEST")

    def test_daily_life_resources_never_serialize_credentials(self):
        values=(PasswordManagerResource("password:local","test","Test").to_resource(),CalendarResource("calendar:test","test","Test").to_resource(),FinancialResource("bank:test","bank_account","test","Test",credential_reference="keychain:secret").to_resource())
        self.assertNotIn("keychain:secret",json.dumps([item.to_dict() for item in values]))

    def test_subscription_relationship_does_not_claim_provider_authority(self):
        resource=FinancialResource("subscription:provider","payment_service","provider","Provider",capabilities=("subscription.inspect","subscription.cancel")).to_resource()
        result=relate_subscription(SubscriptionObservation("obs","Provider",{"amount":"5","currency":"USD"},provider_resource=resource.id,confidence=.8),(resource,))
        self.assertFalse(result["authoritative"]); self.assertIn("subscription.cancel",result["actions"])


if __name__=="__main__": unittest.main()
