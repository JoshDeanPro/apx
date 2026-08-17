import tempfile
import unittest
from pathlib import Path

from apx import APX
from apx.actions import RegisteredAction


def config(tmp_path: Path) -> Path:
    path = tmp_path / "apx.toml"
    path.write_text(
        'version=1\n[[hosts]]\nname="a"\ntransport="local"\n[[hosts]]\nname="unreachable"\ntransport="ssh"\ntarget="nope"\n'
        '[[projects]]\nname="demo"\ndescription="demo"\n'
    )
    return path


class FleetHealthTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.cloud = APX(config(Path(self.temp.name)), plugins=False)
        self.actor = self.cloud.actors.resolve_default()

    def tearDown(self): self.temp.cleanup()

    def test_reports_every_configured_host(self):
        result = self.cloud.run("fleet.health", actor=self.actor)
        self.assertTrue(result.ok, result.error)
        self.assertEqual(set(result.result["hosts"]), {"a", "unreachable"})

    def test_unreachable_host_is_reported_as_a_problem_not_a_crash(self):
        result = self.cloud.run("fleet.health", actor=self.actor)
        self.assertFalse(result.result["healthy"])
        self.assertIn("unreachable", result.result["hosts"])
        self.assertIn("error", result.result["hosts"]["unreachable"])
        self.assertTrue(any("unreachable" in p for p in result.result["problems"]))
        # the other host succeeding is unaffected by the failing one
        self.assertNotIn("error", result.result["hosts"]["a"])

    def test_only_zero_argument_status_actions_are_probed(self):
        self.cloud.actions.register(RegisteredAction(
            "widget.status", "no-arg status", lambda: {"ok": True},
            {"type": "object", "properties": {}, "required": [], "additionalProperties": False}, True, False))
        self.cloud.actions.register(RegisteredAction(
            "widget.instance.status", "requires an id", lambda id: {"ok": True},
            {"type": "object", "properties": {"id": {"type": "string"}}, "required": ["id"], "additionalProperties": False}, True, False))
        result = self.cloud.run("fleet.health", actor=self.actor)
        self.assertIn("widget.status", result.result["providers"])
        self.assertNotIn("widget.instance.status", result.result["providers"])

    def test_failing_provider_status_is_isolated_as_a_problem(self):
        def boom(): raise RuntimeError("provider unreachable")
        self.cloud.actions.register(RegisteredAction(
            "flaky.status", "always fails", boom,
            {"type": "object", "properties": {}, "required": [], "additionalProperties": False}, True, False))
        result = self.cloud.run("fleet.health", actor=self.actor)
        self.assertFalse(result.result["healthy"])
        self.assertIn("error", result.result["providers"]["flaky.status"])
        self.assertTrue(any("flaky.status" in p for p in result.result["problems"]))

    def test_all_healthy_when_everything_succeeds(self):
        single = Path(tempfile.mkdtemp())/"apx.toml"
        single.write_text('version=1\n[[hosts]]\nname="a"\ntransport="local"\n[[projects]]\nname="demo"\ndescription="demo"\n')
        cloud = APX(single, plugins=False)
        result = cloud.run("fleet.health", actor=cloud.actors.resolve_default())
        self.assertTrue(result.result["healthy"])
        self.assertEqual(result.result["problems"], [])


if __name__ == "__main__":
    unittest.main()
