"""Provider conformance, security, lifecycle, receipt, and reversal tests for the APX
Action Provider framework -- run against the real reference provider (examples/subscriptions.py),
not mocks, so these exercise the actual registration/execute/prepare path every real
provider goes through."""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from apx import APX
from apx.examples.subscriptions import build_reference_provider
from apx.providers import ActionProvider, ProviderManifest, validate_provider

AUTH = {"principal_id": "human:owner", "principal_type": "human", "authentication_method": "local_os"}


def write_config(root: Path, extra: str = "") -> Path:
    path = root / "apx.toml"
    path.write_text(
        'version=1\n[[hosts]]\nname="local"\ntransport="local"\n'
        '[[actors]]\nid="agent:reader"\nkind="agent"\nroles=["reader"]\n'
        '[[actors]]\nid="human:owner"\nkind="human"\nroles=["owner"]\n'
        '[[roles]]\nname="reader"\n[[roles.allow]]\naction="subscription.inspect"\n'
        '[[roles]]\nname="owner"\n[[roles.allow]]\naction="subscription.*"\n' + extra
    )
    return path


class ProviderConformanceTests(unittest.TestCase):
    """A provider should be testable independent of any running APX instance."""

    def setUp(self):
        self.provider = build_reference_provider()

    def test_manifest_round_trips(self):
        manifest = self.provider.manifest()
        restored = ProviderManifest.from_dict(manifest.to_dict())
        self.assertEqual({a.id for a in restored.actions}, {a.id for a in manifest.actions})

    def test_action_ids_unique(self):
        manifest = self.provider.manifest()
        ids = [a.id for a in manifest.actions]
        self.assertEqual(len(ids), len(set(ids)))

    def test_input_schemas_describe_objects(self):
        for action in self.provider.manifest().actions:
            self.assertEqual(action.input_schema.get("type"), "object")

    def test_risk_and_confirmation_values_are_valid(self):
        from apx.axp import ACTION_RISKS, CONFIRMATION_LEVELS
        for action in self.provider.manifest().actions:
            self.assertIn(action.risk, ACTION_RISKS)
            self.assertIn(action.confirmation, CONFIRMATION_LEVELS)

    def test_reversible_actions_declare_a_reverse_action_that_exists(self):
        manifest = self.provider.manifest()
        ids = {a.id for a in manifest.actions}
        for action in manifest.actions:
            if action.reversible:
                self.assertTrue(action.reverse_action)
                self.assertIn(action.reverse_action, ids)

    def test_no_secrets_in_manifest(self):
        self.assertEqual(validate_provider(self.provider), [])

    def test_commerce_reciprocity_conformance(self):
        """apx-commerce profile: exposing subscription.start without subscription.cancel
        is a conformance failure -- an APX Commerce provider can't make enrollment
        machine-readable while hiding the cancellation path."""
        broken = ActionProvider("broken.local", "Broken Commerce", provenance="local_component", profiles=("apx-commerce",))
        schema = {"type": "object", "properties": {}, "additionalProperties": False}

        @broken.action("subscription.start", risk="financial", confirmation="transaction", idempotent=False)
        def start(): return {}

        errors = validate_provider(broken)
        self.assertTrue(any("subscription.cancel" in error for error in errors))

    def test_idempotency_is_always_resolved_to_a_concrete_bool(self):
        """RegisteredAction._idempotent() infers from read_only whenever a provider
        doesn't declare it explicitly -- so validate_provider's "idempotency must be
        declared" check is a defensive backstop; by the time a manifest exists,
        idempotent is always True/False, never left ambiguous."""
        for action in self.provider.manifest().actions:
            self.assertIsInstance(action.idempotent, bool)


class ProviderLifecycleTests(unittest.TestCase):
    """DISCOVER -> PREPARE -> AUTHORIZE -> EXECUTE -> VERIFY -> RECEIPT, against a real
    registered APX instance."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        config = write_config(Path(self.tmp.name))
        self.cloud = APX(str(config))
        self.manifest = self.cloud.register_provider(build_reference_provider())

    def tearDown(self):
        self.tmp.cleanup()

    def test_discover_provider_actions_appear_in_registry(self):
        names = {a.name for a in self.cloud.actions.list()}
        self.assertTrue({"subscription.inspect", "subscription.start", "subscription.cancel", "subscription.resume"} <= names)

    def test_prepare_returns_terms_without_executing(self):
        prepared = self.cloud.prepare("subscription.start", actor="human:owner", plan="pro")
        self.assertEqual(prepared.confirmation_required, "transaction")
        self.assertIsNotNone(prepared.cost)
        # prepare must not have changed state
        result = self.cloud.run("subscription.inspect", actor="agent:reader")
        self.assertFalse(result.result["active"])

    def test_read_action_requires_no_confirmation(self):
        result = self.cloud.run("subscription.inspect", actor="agent:reader")
        self.assertTrue(result.ok)
        self.assertEqual(result.status, "completed")

    def test_transaction_action_without_confirmation_is_authorization_required(self):
        result = self.cloud.run("subscription.start", actor="human:owner", auth_context=AUTH, plan="pro")
        self.assertEqual(result.status, "authorization_required")
        self.assertFalse(result.ok)

    def test_transaction_action_with_matching_terms_completes_and_verifies_state(self):
        prepared = self.cloud.prepare("subscription.start", actor="human:owner", plan="pro")
        result = self.cloud.run(
            "subscription.start", actor="human:owner", auth_context=AUTH, plan="pro",
            confirmation={"level": "transaction", "confirmed": True, "terms": prepared.confirmation_terms},
        )
        self.assertTrue(result.ok)
        self.assertEqual(result.status, "completed")
        state = self.cloud.run("subscription.inspect", actor="agent:reader").result
        self.assertTrue(state["active"])
        self.assertEqual(state["plan"], "pro")

    def test_reversal_round_trip(self):
        prepared = self.cloud.prepare("subscription.start", actor="human:owner", plan="pro")
        self.cloud.run("subscription.start", actor="human:owner", auth_context=AUTH, plan="pro",
                        confirmation={"level": "transaction", "confirmed": True, "terms": prepared.confirmation_terms})
        cancel = self.cloud.run("subscription.cancel", actor="human:owner", auth_context=AUTH, confirmation={"level": "confirm", "confirmed": True})
        self.assertTrue(cancel.ok)
        self.assertFalse(self.cloud.run("subscription.inspect", actor="agent:reader").result["renewal"])
        resume = self.cloud.run("subscription.resume", actor="human:owner", auth_context=AUTH, confirmation={"level": "confirm", "confirmed": True})
        self.assertTrue(resume.ok)
        self.assertTrue(self.cloud.run("subscription.inspect", actor="agent:reader").result["renewal"])


class ReceiptTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        config = write_config(Path(self.tmp.name))
        self.cloud = APX(str(config))
        self.cloud.register_provider(build_reference_provider())

    def tearDown(self):
        self.tmp.cleanup()

    def test_failed_action_carries_no_receipt(self):
        """An unrelated action failure (unknown host) never gets a receipt -- receipts
        are for consequential actions that actually ran, not every ActionResult."""
        result = self.cloud.run("host.status", actor="human:owner", host="no-such-host")
        self.assertFalse(result.ok)
        self.assertIsNone(result.receipt)

    def test_consequential_action_returns_a_receipt(self):
        prepared = self.cloud.prepare("subscription.start", actor="human:owner", plan="pro")
        self.cloud.run("subscription.start", actor="human:owner", auth_context=AUTH, plan="pro",
                        confirmation={"level": "transaction", "confirmed": True, "terms": prepared.confirmation_terms})
        cancel = self.cloud.run("subscription.cancel", actor="human:owner", auth_context=AUTH, confirmation={"level": "confirm", "confirmed": True})
        self.assertIsNotNone(cancel.receipt)
        self.assertEqual(cancel.receipt.action, "subscription.cancel")
        self.assertEqual(cancel.receipt.provider, "reference.local")
        self.assertEqual(cancel.receipt.status, "completed")

    def test_receipt_records_verification_status(self):
        prepared = self.cloud.prepare("subscription.start", actor="human:owner", plan="pro")
        self.cloud.run("subscription.start", actor="human:owner", auth_context=AUTH, plan="pro",
                        confirmation={"level": "transaction", "confirmed": True, "terms": prepared.confirmation_terms})
        cancel = self.cloud.run("subscription.cancel", actor="human:owner", auth_context=AUTH, confirmation={"level": "confirm", "confirmed": True})
        self.assertEqual(cancel.receipt.verification_status, "verified")

    def test_receipt_carries_reversal_metadata(self):
        prepared = self.cloud.prepare("subscription.start", actor="human:owner", plan="pro")
        self.cloud.run("subscription.start", actor="human:owner", auth_context=AUTH, plan="pro",
                        confirmation={"level": "transaction", "confirmed": True, "terms": prepared.confirmation_terms})
        cancel = self.cloud.run("subscription.cancel", actor="human:owner", auth_context=AUTH, confirmation={"level": "confirm", "confirmed": True})
        self.assertEqual(cancel.receipt.reversal, {"available": True, "action": "subscription.resume"})

    def test_no_secrets_in_receipt(self):
        prepared = self.cloud.prepare("subscription.start", actor="human:owner", plan="pro")
        result = self.cloud.run("subscription.start", actor="human:owner", auth_context=AUTH, plan="pro",
                                 confirmation={"level": "transaction", "confirmed": True, "terms": prepared.confirmation_terms})
        receipt_json = str(result.receipt.to_dict())
        for marker in ("password", "secret", "token", "api_key"):
            self.assertNotIn(marker, receipt_json.lower())


class SecurityTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        config = write_config(Path(self.tmp.name))
        self.cloud = APX(str(config))
        self.cloud.register_provider(build_reference_provider())

    def tearDown(self):
        self.tmp.cleanup()

    def test_unauthorized_actor_is_rejected(self):
        result = self.cloud.run("subscription.cancel", actor="agent:reader", auth_context=AUTH, confirmation={"level": "confirm", "confirmed": True})
        self.assertFalse(result.ok)
        self.assertEqual(result.error.code, "permission_denied")

    def test_explicit_deny_wins_over_allow(self):
        config = write_config(
            Path(self.tmp.name),
            extra='[[roles]]\nname="denied"\n[[roles.deny]]\naction="subscription.cancel"\n'
                  '[[actors]]\nid="agent:denied"\nkind="agent"\nroles=["owner","denied"]\n',
        )
        cloud = APX(str(config))
        cloud.register_provider(build_reference_provider())
        result = cloud.run("subscription.cancel", actor="agent:denied", auth_context=AUTH, confirmation={"level": "confirm", "confirmed": True})
        self.assertFalse(result.ok)
        self.assertEqual(result.error.code, "permission_denied")

    def test_confirmation_required_action_cannot_execute_without_confirmation(self):
        result = self.cloud.run("subscription.cancel", actor="human:owner", auth_context=AUTH)
        self.assertEqual(result.status, "authorization_required")

    def test_wrong_confirmation_level_is_rejected(self):
        result = self.cloud.run("subscription.cancel", actor="human:owner", auth_context=AUTH, confirmation={"level": "delegated", "confirmed": True})
        self.assertEqual(result.status, "authorization_required")

    def test_transaction_action_cannot_execute_without_exact_confirmed_terms(self):
        result = self.cloud.run(
            "subscription.start", actor="human:owner", auth_context=AUTH, plan="pro",
            confirmation={"level": "transaction", "confirmed": True, "terms": {"amount": "0.01"}},
        )
        self.assertEqual(result.status, "authorization_required")

    def test_expired_confirmation_is_rejected(self):
        result = self.cloud.run(
            "subscription.cancel", actor="human:owner", auth_context=AUTH,
            confirmation={"level": "confirm", "confirmed": True, "expires_at": "2000-01-01T00:00:00+00:00"},
        )
        self.assertEqual(result.status, "authorization_required")

    def test_replayed_authorization_id_is_rejected(self):
        prepared = self.cloud.prepare("subscription.start", actor="human:owner", plan="pro")
        self.cloud.run("subscription.start", actor="human:owner", auth_context=AUTH, plan="pro",
                        confirmation={"level": "transaction", "confirmed": True, "terms": prepared.confirmation_terms})
        first = self.cloud.run("subscription.cancel", actor="human:owner", auth_context=AUTH,
                                confirmation={"level": "confirm", "confirmed": True, "authorization_id": "replay-test"})
        second = self.cloud.run("subscription.resume", actor="human:owner", auth_context=AUTH,
                                 confirmation={"level": "confirm", "confirmed": True, "authorization_id": "replay-test"})
        self.assertTrue(first.ok)
        self.assertEqual(second.status, "authorization_required")

    def test_revoked_credential_is_rejected(self):
        from apx.axp import ActionRequest, CredentialHandle
        handle = CredentialHandle(id="cred-1", mode="bearer", issuer="apx", audience="reference.local", revoked=True)
        request = ActionRequest(action="subscription.inspect", actor="agent:reader", credential=handle)
        result = self.cloud.execute(request)
        self.assertFalse(result.ok)
        self.assertEqual(result.error.code, "credential_revoked")

    def test_provider_actor_descriptor_excludes_unrelated_data(self):
        """The descriptor a provider would be told carries only actor/owner/client/device/
        roles -- never conversation, system prompt, or unrelated profiles."""
        from apx.axp import ActionRequest
        request = ActionRequest(action="subscription.inspect", actor="agent:reader", client="op", device="machine:mac")
        descriptor = self.cloud.provider_actor(request)
        payload = descriptor.to_dict()
        self.assertEqual(payload["id"], "agent:reader")
        self.assertEqual(set(payload) - {"apx", "type"}, {"kind", "id", "owner", "client", "device", "roles", "delegated_by", "permissions"})


class ManifestSecurityTests(unittest.TestCase):
    def test_manifest_rejects_secret_shaped_fields(self):
        provider = ActionProvider("leaky.local", "Leaky Provider", provenance="local_component",
                                   metadata={"api_key": "sk-shouldnotbehere"})
        errors = validate_provider(provider)
        self.assertTrue(any("secret" in error for error in errors))


if __name__ == "__main__":
    unittest.main()
