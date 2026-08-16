import tempfile
import unittest
from pathlib import Path

from apx import APX


def config(tmp_path: Path) -> Path:
    path=tmp_path/"apx.toml"
    path.write_text('version=1\n[[hosts]]\nname="test"\ntransport="local"\n')
    return path


class StateStoreTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.cloud=APX(config(Path(self.temp.name)),plugins=False)

    def tearDown(self): self.temp.cleanup()

    def test_default_state_is_normal(self):
        self.assertEqual(self.cloud.state.get(),"normal")

    def test_set_persists_and_records_history(self):
        entry=self.cloud.state.set("incident","suspicious login","human:owner")
        self.assertEqual(entry["from"],"normal"); self.assertEqual(entry["to"],"incident")
        self.assertEqual(self.cloud.state.get(),"incident")
        self.assertEqual(self.cloud.state.status()["history"][-1],entry)

    def test_state_set_action_emits_system_state_changed_and_security_events(self):
        events=[]; self.cloud.events.subscribe("*",events.append,owner="test")
        result=self.cloud.run("state.set",name="incident",reason="test")
        self.assertTrue(result.ok)
        names=[e.name for e in events]
        self.assertIn("system.state_changed",names)
        self.assertIn("security.incident_started",names)

    def test_lockdown_ended_emitted_on_exit(self):
        self.cloud.run("state.set",name="lockdown",reason="breach")
        events=[]; self.cloud.events.subscribe("*",events.append,owner="test")
        self.cloud.run("state.set",name="normal",reason="resolved")
        self.assertIn("security.lockdown_ended",[e.name for e in events])

    def test_break_glass_emits_event_without_mutating_state(self):
        events=[]; self.cloud.events.subscribe("*",events.append,owner="test")
        result=self.cloud.run("security.break_glass",reason="prod is down")
        self.assertTrue(result.ok)
        self.assertIn("security.break_glass_started",[e.name for e in events])
        self.assertEqual(self.cloud.state.get(),"normal")


if __name__ == "__main__": unittest.main()
