import tempfile
import unittest
from pathlib import Path

from apx import APX
from apx.enrollment import EnrollmentError, EnrollmentStore


def config(tmp_path: Path, extra: str = "") -> Path:
    path=tmp_path/"apx.toml"
    path.write_text('version=1\n[[hosts]]\nname="test"\ntransport="local"\n'+extra)
    return path


class EnrollmentStoreTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.config_path=Path(self.temp.name)/"apx.toml"
        self.store=EnrollmentStore(self.config_path)

    def tearDown(self): self.temp.cleanup()

    def test_manual_mode_leaves_pending(self):
        record=self.store.request(machine_id="machine:mac",runtime="",mode="manual")
        self.assertEqual(record["status"],"pending")

    def test_disabled_mode_refuses_request(self):
        with self.assertRaises(EnrollmentError): self.store.request(machine_id="machine:mac",runtime="",mode="disabled")

    def test_automatic_mode_only_applies_when_explicitly_requested(self):
        # the caller (cloud.py) resolves mode from config -- "manual" (the default) never auto-approves
        manual=self.store.request(machine_id="machine:mac",runtime="",mode="manual")
        self.assertEqual(manual["status"],"pending")
        automatic=self.store.request(machine_id="machine:mac",runtime="",mode="automatic")
        self.assertEqual(automatic["status"],"approved")
        self.assertEqual(automatic["resolved_by"],"automatic-policy")

    def test_approve_deny_cancel(self):
        pending=self.store.request(machine_id="machine:mac",runtime="")
        approved=self.store.approve(pending["id"],resolved_by="human:ethan")
        self.assertEqual(approved["status"],"approved"); self.assertIsNotNone(approved["resolved_at"])
        with self.assertRaises(EnrollmentError): self.store.deny(pending["id"])  # already resolved

        other=self.store.request(machine_id="machine:mac",runtime="")
        denied=self.store.deny(other["id"],resolved_by="human:ethan")
        self.assertEqual(denied["status"],"denied")

        third=self.store.request(machine_id="machine:mac",runtime="")
        cancelled=self.store.cancel(third["id"])
        self.assertEqual(cancelled["status"],"cancelled")

    def test_approve_records_openpower_ref_when_provided(self):
        pending=self.store.request(machine_id="machine:mac",runtime="")
        approved=self.store.approve(pending["id"],openpower_ref="agent:op-uuid-1")
        self.assertEqual(approved["openpower_ref"],"agent:op-uuid-1")

    def test_list_filters_by_status(self):
        a=self.store.request(machine_id="m",runtime="")
        b=self.store.request(machine_id="m",runtime="codex")
        self.store.approve(a["id"])
        self.assertEqual([r["id"] for r in self.store.list(status="pending")],[b["id"]])

    def test_persists_across_instances(self):
        record=self.store.request(machine_id="machine:mac",runtime="")
        reloaded=EnrollmentStore(self.config_path)
        self.assertEqual(reloaded.get(record["id"])["machine_id"],"machine:mac")


class EnrollmentActionsTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()

    def tearDown(self): self.temp.cleanup()

    def test_default_mode_is_manual_and_requires_approval(self):
        cloud=APX(config(Path(self.temp.name)),plugins=False)
        result=cloud.run("identity.enrollment.request",machine_id="machine:mac",runtime="")
        self.assertTrue(result.ok); self.assertEqual(result.result["status"],"pending")

    def test_configured_automatic_mode_approves_immediately(self):
        cloud=APX(config(Path(self.temp.name),'[auth]\nenrollment_mode="automatic"\n'),plugins=False)
        result=cloud.run("identity.enrollment.request",machine_id="machine:mac",runtime="")
        self.assertEqual(result.result["status"],"approved")

    def test_configured_disabled_mode_refuses(self):
        cloud=APX(config(Path(self.temp.name),'[auth]\nenrollment_mode="disabled"\n'),plugins=False)
        result=cloud.run("identity.enrollment.request",machine_id="machine:mac",runtime="")
        self.assertFalse(result.ok)

    def test_enrollment_events_emitted(self):
        cloud=APX(config(Path(self.temp.name)),plugins=False)
        events=[]; cloud.events.subscribe("*",events.append,owner="test")
        request=cloud.run("identity.enrollment.request",machine_id="machine:mac",runtime="").result
        cloud.run("identity.enrollment.approve",request_id=request["id"],approved_by="human:ethan")
        names=[e.name for e in events]
        self.assertIn("identity.enrollment_requested",names)
        self.assertIn("identity.enrollment_approved",names)

    def test_deny_event(self):
        cloud=APX(config(Path(self.temp.name)),plugins=False)
        events=[]; cloud.events.subscribe("*",events.append,owner="test")
        request=cloud.run("identity.enrollment.request",machine_id="machine:mac",runtime="").result
        cloud.run("identity.enrollment.deny",request_id=request["id"])
        self.assertIn("identity.enrollment_denied",[e.name for e in events])


if __name__ == "__main__": unittest.main()
