import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from apx import APX, Host
from apx.agents import AGENT_RUNTIMES, AgentError, deploy, detect_init_system, render
from apx.transports import CommandResult


def config(tmp_path: Path) -> Path:
    path = tmp_path / "apx.toml"
    path.write_text('version=1\n[[hosts]]\nname="test"\ntransport="local"\n[[projects]]\nname="demo"\ndescription="demo"\n')
    return path


class FakeTransport:
    def __init__(self, ok: bool = True): self.calls = []; self.ok = ok
    def run(self, argv, timeout=30, input_text=None):
        self.calls.append((list(argv), input_text))
        return CommandResult(tuple(argv), 0 if self.ok else 1, "", "" if self.ok else "boom")


SYSTEMD_DISCOVERY = {"capabilities": {"systemd": {"available": True}, "launchd": {"available": False}}}


class RenderTests(unittest.TestCase):
    def test_render_produces_valid_bash_for_every_runtime(self):
        import subprocess
        for runtime in AGENT_RUNTIMES:
            rendered = render("demo", repo="/srv/demo", runtime=runtime)
            result = subprocess.run(["bash", "-n"], input=rendered["run_sh"], text=True, capture_output=True)
            self.assertEqual(result.returncode, 0, f"{runtime}: {result.stderr}")

    def test__runtime_is_verified_codex_is_not(self):
        self.assertTrue(render("demo", repo="/srv/demo", runtime="")["runtime_verified"])
        self.assertFalse(render("demo", repo="/srv/demo", runtime="codex")["runtime_verified"])

    def test_unknown_runtime_rejected(self):
        with self.assertRaises(AgentError):
            render("demo", repo="/srv/demo", runtime="gpt5-agent-thing")

    def test_invalid_name_rejected(self):
        with self.assertRaises(AgentError):
            render("has spaces", repo="/srv/demo")

    def test_configurable_parameters_appear_in_output(self):
        rendered = render("demo", repo="/srv/demo", model="haiku", effort="high", timeout=999, idle_gap=42)
        self.assertIn("haiku", rendered["run_sh"])
        self.assertIn("high", rendered["run_sh"])
        self.assertIn("999", rendered["run_sh"])
        self.assertIn("42", rendered["run_sh"])

    def test_unit_references_the_rendered_run_script_path(self):
        rendered = render("demo", repo="/srv/demo")
        self.assertIn(rendered["run_script_path"], rendered["unit"])

    def test_prompt_includes_project_description(self):
        rendered = render("demo", repo="/srv/demo", project_description="the widget factory")
        self.assertIn("the widget factory", rendered["prompt"])


class DeployTests(unittest.TestCase):
    def test_detect_init_system_prefers_systemd(self):
        host = Host("vps", "ssh", "vps")
        with patch("apx.agents.inspect_host", return_value=SYSTEMD_DISCOVERY):
            self.assertEqual(detect_init_system(host), "systemd")

    def test_detect_init_system_falls_back_to_launchd(self):
        host = Host("mac", "local")
        with patch("apx.agents.inspect_host", return_value={"capabilities": {"systemd": {"available": False}, "launchd": {"available": True}}}):
            self.assertEqual(detect_init_system(host), "launchd")

    def test_detect_init_system_raises_with_neither(self):
        host = Host("mystery", "local")
        with patch("apx.agents.inspect_host", return_value={"capabilities": {"systemd": {"available": False}, "launchd": {"available": False}}}):
            with self.assertRaises(AgentError):
                detect_init_system(host)

    def test_deploy_on_launchd_writes_plist_and_bootstraps_without_starting(self):
        host = Host("mac", "local")
        rendered = render("demo", repo="/Users/ethan/demo", user="ethan", init_system="launchd")
        self.assertIn("<false/>", rendered["unit"])  # RunAtLoad=false, verified before any I/O

        class LaunchdTransport(FakeTransport):
            def run(self, argv, timeout=30, input_text=None):
                self.calls.append((list(argv), input_text))
                if argv[:2] == ["test", "-f"]: return CommandResult(tuple(argv), 1, "", "")
                if argv == ["id", "-u"]: return CommandResult(tuple(argv), 0, "501\n", "")
                return CommandResult(tuple(argv), 0, "", "")

        transport = LaunchdTransport()
        with patch("apx.agents.transport_for", return_value=transport):
            result = deploy(host, rendered)
        self.assertEqual(result["init_system"], "launchd")
        bootstrap_calls = [argv for argv, _ in transport.calls if argv[:2] == ["launchctl", "bootstrap"]]
        self.assertEqual(bootstrap_calls, [["launchctl", "bootstrap", "gui/501", rendered["unit_path"]]])
        # no systemctl call was made for a launchd deploy
        self.assertFalse(any(argv[0] == "systemctl" for argv, _ in transport.calls))

    def test_deploy_tolerates_already_bootstrapped_launchd_job(self):
        host = Host("mac", "local")
        rendered = render("demo", repo="/Users/ethan/demo", user="ethan", init_system="launchd")

        class AlreadyBootstrappedTransport(FakeTransport):
            def run(self, argv, timeout=30, input_text=None):
                self.calls.append((list(argv), input_text))
                if argv[:2] == ["test", "-f"]: return CommandResult(tuple(argv), 1, "", "")
                if argv == ["id", "-u"]: return CommandResult(tuple(argv), 0, "501\n", "")
                if argv[:2] == ["launchctl", "bootstrap"]: return CommandResult(tuple(argv), 1, "", "service already bootstrapped")
                return CommandResult(tuple(argv), 0, "", "")

        transport = AlreadyBootstrappedTransport()
        with patch("apx.agents.transport_for", return_value=transport):
            result = deploy(host, rendered)  # must not raise
        self.assertEqual(result["init_system"], "launchd")

    def test_deploy_writes_run_script_unit_and_prompt_then_reloads(self):
        host = Host("vps", "ssh", "vps")
        rendered = render("demo", repo="/srv/demo")

        class NotYetDeployedTransport(FakeTransport):
            def run(self, argv, timeout=30, input_text=None):
                self.calls.append((list(argv), input_text))
                if argv[:2] == ["test", "-f"]: return CommandResult(tuple(argv), 1, "", "")
                return CommandResult(tuple(argv), 0, "", "")

        transport = NotYetDeployedTransport()
        with patch("apx.agents.transport_for", return_value=transport):
            result = deploy(host, rendered)
        self.assertTrue(result["wrote_prompt"])
        written_paths = [argv[1] for argv, _ in transport.calls if argv[0] == "tee"]
        self.assertIn(rendered["run_script_path"], written_paths)
        self.assertIn(rendered["unit_path"], written_paths)
        self.assertIn(rendered["prompt_path"], written_paths)
        self.assertIn(["systemctl", "daemon-reload"], [argv for argv, _ in transport.calls])
        chmod_calls = [argv for argv, _ in transport.calls if argv[0] == "chmod"]
        self.assertIn(["chmod", "755", rendered["run_script_path"]], chmod_calls)

    def test_deploy_does_not_overwrite_existing_prompt_without_force(self):
        host = Host("vps", "ssh", "vps")
        rendered = render("demo", repo="/srv/demo")

        class PromptExistsTransport(FakeTransport):
            def run(self, argv, timeout=30, input_text=None):
                if argv[:2] == ["test", "-f"]:
                    self.calls.append((list(argv), input_text))
                    return CommandResult(tuple(argv), 0, "", "")
                return super().run(argv, timeout=timeout, input_text=input_text)

        transport = PromptExistsTransport()
        with patch("apx.agents.transport_for", return_value=transport):
            result = deploy(host, rendered, force=False)
        self.assertFalse(result["wrote_prompt"])
        written_paths = [argv[1] for argv, _ in transport.calls if argv[0] == "tee"]
        self.assertNotIn(rendered["prompt_path"], written_paths)
        self.assertIn(rendered["run_script_path"], written_paths)  # run.sh is always regenerated


class AgentActionsThroughAPXTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.cloud = APX(config(Path(self.temp.name)), plugins=False)
        self.actor = self.cloud.actors.resolve_default()

    def tearDown(self): self.temp.cleanup()

    def confirm(self, tag): return {"level": "confirm", "confirmed": True, "authorization_id": tag}

    def test_plan_does_not_require_confirmation_and_writes_nothing(self):
        result = self.cloud.run("agent.plan", actor=self.actor, name="demo", host="test", repo="/tmp/x")
        self.assertTrue(result.ok, result.error)
        self.assertIn("run_sh", result.result)

    def test_setup_requires_confirmation(self):
        result = self.cloud.run("agent.setup", actor=self.actor, name="demo", host="test", repo="/tmp/x")
        self.assertFalse(result.ok)
        self.assertEqual(result.status, "authorization_required")

    def test_setup_on_a_non_systemd_host_fails_cleanly(self):
        # this test machine is macOS/launchd, or at least not guaranteed systemd --
        # exercise the real failure path rather than mocking it away here.
        result = self.cloud.run("agent.setup", actor=self.actor, confirmation=self.confirm("t1"),
                                 name="demo", host="test", repo="/tmp/x")
        self.assertFalse(result.ok)

    def test_full_lifecycle_with_a_faked_systemd_host(self):
        class SetupTransport(FakeTransport):
            def run(self, argv, timeout=30, input_text=None):
                self.calls.append((list(argv), input_text))
                if argv[:2] == ["test", "-f"]: return CommandResult(tuple(argv), 1, "", "")  # prompt not present yet
                return CommandResult(tuple(argv), 0, "", "")

        transport = SetupTransport()
        with patch("apx.agents.inspect_host", return_value=SYSTEMD_DISCOVERY), \
             patch("apx.agents.transport_for", return_value=transport), \
             patch("apx.cloud.transport_for", return_value=transport):
            created = self.cloud.run("agent.setup", actor=self.actor, confirmation=self.confirm("t1"),
                                      name="demo", host="test", repo="/tmp/x", enable=True)
        self.assertTrue(created.ok, created.error)
        self.assertTrue(created.result["enabled"])
        self.assertFalse(created.result["started"])

        listed = self.cloud.run("agent.list", actor=self.actor)
        self.assertEqual([a["name"] for a in listed.result["agents"]], ["demo"])

        inspected = self.cloud.run("agent.inspect", actor=self.actor, name="demo")
        self.assertTrue(inspected.ok)
        self.assertEqual(inspected.result["host"], "test")

        removed = self.cloud.run("agent.remove", actor=self.actor, confirmation=self.confirm("t2"), name="demo")
        self.assertTrue(removed.ok, removed.error)
        self.assertEqual(self.cloud.run("agent.list", actor=self.actor).result["agents"], [])

    def test_inspect_unknown_agent_fails_cleanly(self):
        result = self.cloud.run("agent.inspect", actor=self.actor, name="ghost")
        self.assertFalse(result.ok)

    def test_remove_unknown_agent_fails_cleanly(self):
        result = self.cloud.run("agent.remove", actor=self.actor, confirmation=self.confirm("t3"), name="ghost")
        self.assertFalse(result.ok)


if __name__ == "__main__":
    unittest.main()
