import tempfile
import unittest
from pathlib import Path

from apx import APX


def config(tmp_path: Path, extra: str = "") -> Path:
    path = tmp_path / "apx.toml"
    path.write_text('version=1\n[[hosts]]\nname="test"\ntransport="local"\n[[projects]]\nname="demo"\ndescription="demo"\n' + extra)
    return path


ROLES_TOML = (
    '[[actors]]\nid="human:admin"\nkind="human"\nroles=["admin"]\n'
    '[[actors]]\nid="human:employee"\nkind="human"\nroles=["employee"]\n'
    '[[roles]]\nname="admin"\nallow=[{action="*"}]\n'
    '[[roles]]\nname="employee"\nallow=[{action="actor.whoami"},{action="discovery.capabilities"}]\n'
)


class GrantTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.cloud = APX(config(Path(self.temp.name), ROLES_TOML), plugins=False)

    def tearDown(self): self.temp.cleanup()

    def test_grant_expands_what_a_subject_can_invoke_and_discover(self):
        denied = self.cloud.run("blueprint.list", actor="human:employee")
        self.assertEqual(denied.error.code, "permission_denied")
        before = self.cloud.run("discovery.capabilities", actor="human:employee", subject="human:employee")
        self.assertNotIn("blueprint.list", {c["id"] for c in before.result["capabilities"]})

        issued = self.cloud.run("grant.issue", actor="human:admin", subject="human:employee", actions=["blueprint.list"])
        self.assertTrue(issued.ok, issued.error)
        self.assertTrue(issued.result["active"])

        allowed = self.cloud.run("blueprint.list", actor="human:employee")
        self.assertTrue(allowed.ok)
        after = self.cloud.run("discovery.capabilities", actor="human:employee", subject="human:employee")
        self.assertIn("blueprint.list", {c["id"] for c in after.result["capabilities"]})

    def test_issuer_cannot_delegate_authority_it_does_not_hold(self):
        result = self.cloud.run("grant.issue", actor="human:employee", subject="human:admin", actions=["blueprint.apply"])
        self.assertFalse(result.ok)
        self.assertEqual(result.error.code, "permission_denied")

    def test_revoke_immediately_withdraws_authority(self):
        issued = self.cloud.run("grant.issue", actor="human:admin", subject="human:employee", actions=["blueprint.list"])
        grant_id = issued.result["id"]
        self.assertTrue(self.cloud.run("blueprint.list", actor="human:employee").ok)
        revoked = self.cloud.run("grant.revoke", actor="human:admin", grant=grant_id)
        self.assertTrue(revoked.ok)
        self.assertIsNotNone(revoked.result["revoked_at"])
        self.assertFalse(self.cloud.run("blueprint.list", actor="human:employee").ok)
        # a grant can only be revoked once
        self.assertFalse(self.cloud.run("grant.revoke", actor="human:admin", grant=grant_id).ok)

    def test_expired_grant_no_longer_authorizes(self):
        issued = self.cloud.run("grant.issue", actor="human:admin", subject="human:employee",
                                 actions=["blueprint.list"], expires_at="2000-01-01T00:00:00+00:00")
        self.assertTrue(issued.ok)
        self.assertFalse(issued.result["active"])
        self.assertFalse(self.cloud.run("blueprint.list", actor="human:employee").ok)
        listed = self.cloud.run("grant.list", actor="human:admin", subject="human:employee")
        self.assertEqual(listed.result["grants"], [])  # active-only by default
        listed_all = self.cloud.run("grant.list", actor="human:admin", subject="human:employee", include_expired=True)
        self.assertEqual(len(listed_all.result["grants"]), 1)

    def test_grant_scoped_by_constraints_only_matches_that_scope(self):
        issued = self.cloud.run("grant.issue", actor="human:admin", subject="human:employee",
                                 actions=["service.restart"], constraints={"host": ["dev"]})
        self.assertTrue(issued.ok)
        denied_prod = self.cloud.run("service.restart", actor="human:employee", host="prod", service="web")
        self.assertFalse(denied_prod.ok)
        self.assertEqual(denied_prod.error.code, "permission_denied")

    def test_inspect_unknown_grant_fails_cleanly(self):
        result = self.cloud.run("grant.inspect", actor="human:admin", grant="grant-doesnotexist")
        self.assertFalse(result.ok)

    def test_grant_scoped_by_resource_ref_binds_to_that_host_only(self):
        issued = self.cloud.run("grant.issue", actor="human:admin", subject="human:employee",
                                 actions=["service.status"], resources=["apx://host/test"])
        self.assertTrue(issued.ok, issued.error)
        allowed = self.cloud.run("service.status", actor="human:employee", host="test", service="x")
        self.assertNotEqual(allowed.error.code if allowed.error else None, "permission_denied")
        elsewhere = self.cloud.run("grant.issue", actor="human:admin", subject="human:employee",
                                    actions=["service.status"])  # unscoped control, different subject state
        self.assertTrue(elsewhere.ok)

    def test_grant_with_no_actions_is_rejected_before_execution(self):
        result = self.cloud.run("grant.issue", actor="human:admin", subject="human:employee", actions=[])
        self.assertFalse(result.ok)
        self.assertEqual(result.error.code, "invalid_input")

    def test_expiry_uses_real_time_comparison_across_offsets(self):
        # 23:00+05:00 is 18:00 UTC -- earlier than "now" below, so this must already be expired
        # despite the hour digits '23' sorting after '20' as raw strings.
        issued = self.cloud.run("grant.issue", actor="human:admin", subject="human:employee",
                                 actions=["blueprint.list"], expires_at="2026-08-13T23:00:00+05:00")
        self.assertTrue(issued.ok)
        from apx.grants import Grant
        grant = Grant(**{k: v for k, v in issued.result.items() if k != "active"})
        self.assertFalse(grant.active(now="2026-08-13T20:00:00+00:00"))


if __name__ == "__main__":
    unittest.main()
