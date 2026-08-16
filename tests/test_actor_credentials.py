import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from apx import APX
from apx.credentials import ActorCredentialError, ActorCredentialStore


def config(tmp_path: Path, extra: str = "") -> Path:
    path=tmp_path/"apx.toml"
    path.write_text('version=1\n[[hosts]]\nname="test"\ntransport="local"\n'+extra)
    return path


def fingerprint(value: str) -> str: return hashlib.sha256(value.encode()).hexdigest()[:16]


class ActorCredentialStoreTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.config_path=Path(self.temp.name)/"apx.toml"
        self.store=ActorCredentialStore(self.config_path)

    def tearDown(self): self.temp.cleanup()

    def test_issue_defaults_to_active_with_no_plaintext(self):
        record=self.store.issue("agent::mac",fingerprint=fingerprint("super-secret-value"))
        self.assertEqual(record["state"],"active")
        self.assertNotIn("super-secret-value",json.dumps(record))

    def test_invalid_type_rejected(self):
        with self.assertRaises(ActorCredentialError): self.store.issue("agent::mac",type="not-a-real-type")

    def test_rotate_keeps_old_active_material_marked_rotating_not_revoked(self):
        original=self.store.issue("agent::mac",fingerprint=fingerprint("v1"))
        result=self.store.rotate(original["id"],fingerprint=fingerprint("v2"))
        self.assertEqual(result["previous"]["state"],"rotating")
        self.assertEqual(result["current"]["state"],"active")
        self.assertEqual(result["current"]["version"],2)
        self.assertEqual(result["current"]["replaces"],original["id"])

    def test_old_credential_only_revoked_after_explicit_confirmation(self):
        original=self.store.issue("agent::mac",fingerprint=fingerprint("v1"))
        self.store.rotate(original["id"],fingerprint=fingerprint("v2"))
        still_rotating=self.store.inspect(original["id"])
        self.assertEqual(still_rotating["state"],"rotating")  # not revoked yet
        confirmed=self.store.confirm_rotation(original["id"])
        self.assertEqual(confirmed["state"],"revoked")

    def test_cannot_rotate_a_non_active_credential(self):
        original=self.store.issue("agent::mac")
        self.store.revoke(original["id"])
        with self.assertRaises(ActorCredentialError): self.store.rotate(original["id"])

    def test_cannot_confirm_rotation_that_was_never_started(self):
        original=self.store.issue("agent::mac")
        with self.assertRaises(ActorCredentialError): self.store.confirm_rotation(original["id"])

    def test_revoke_is_immediate_and_independent_of_rotation(self):
        record=self.store.issue("agent::mac")
        revoked=self.store.revoke(record["id"])
        self.assertEqual(revoked["state"],"revoked")

    def test_list_for_filters_by_principal(self):
        self.store.issue("agent::mac")
        self.store.issue("human:owner")
        self.assertEqual(len(self.store.list_for("agent::mac")),1)

    def test_expires_lazily_computed_on_read(self):
        from datetime import datetime, timedelta, timezone
        past=(datetime.now(timezone.utc)-timedelta(days=1)).isoformat()
        record=self.store.issue("agent::mac",expires=past)
        self.assertEqual(self.store.inspect(record["id"])["state"],"expired")

    def test_persists_across_instances(self):
        record=self.store.issue("agent::mac",fingerprint="fp1")
        reloaded=ActorCredentialStore(self.config_path)
        self.assertEqual(reloaded.inspect(record["id"])["fingerprint"],"fp1")


class ActorCredentialActionsTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.cloud=APX(config(Path(self.temp.name)),plugins=False)

    def tearDown(self): self.temp.cleanup()

    def test_issue_rotate_confirm_revoke_via_actions(self):
        issued=self.cloud.run("credential.issue",principal="agent::mac",fingerprint="fp1").result
        rotated=self.cloud.run("credential.rotate",credential_id=issued["id"],fingerprint="fp2").result
        self.assertEqual(rotated["previous"]["state"],"rotating")
        confirmed=self.cloud.run("credential.confirm_rotation",previous_credential_id=issued["id"]).result
        self.assertEqual(confirmed["state"],"revoked")
        second=self.cloud.run("credential.inspect",credential_id=rotated["current"]["id"])
        self.assertEqual(second.result["state"],"active")

    def test_revoked_credential_stays_revoked(self):
        issued=self.cloud.run("credential.issue",principal="agent::mac").result
        self.cloud.run("credential.revoke",credential_id=issued["id"])
        inspected=self.cloud.run("credential.inspect",credential_id=issued["id"])
        self.assertEqual(inspected.result["state"],"revoked")

    def test_events_never_include_a_fingerprint_derived_from_a_leaked_secret_marker(self):
        events=[]; self.cloud.events.subscribe("*",events.append,owner="test")
        self.cloud.run("credential.issue",principal="agent::mac",fingerprint=fingerprint("do-not-leak-this-value"))
        blob=json.dumps([e.to_dict() for e in events])
        self.assertNotIn("do-not-leak-this-value",blob)

    def test_named_events_emitted(self):
        events=[]; self.cloud.events.subscribe("*",events.append,owner="test")
        issued=self.cloud.run("credential.issue",principal="agent::mac").result
        self.cloud.run("credential.rotate",credential_id=issued["id"])
        self.cloud.run("credential.revoke",credential_id=issued["id"])
        names=[e.name for e in events]
        self.assertIn("credential.created",names); self.assertIn("credential.rotated",names); self.assertIn("credential.revoked",names)


if __name__ == "__main__": unittest.main()
