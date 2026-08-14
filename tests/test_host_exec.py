import tempfile
import unittest
from pathlib import Path

from apx import APX


def config(tmp_path: Path) -> Path:
    path = tmp_path / "apx.toml"
    path.write_text('version=1\n[[hosts]]\nname="test"\ntransport="local"\n[[projects]]\nname="demo"\ndescription="demo"\n')
    return path


class HostExecTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.cloud = APX(config(Path(self.temp.name)), plugins=False)
        self.actor = self.cloud.actors.resolve_default()

    def tearDown(self): self.temp.cleanup()

    def run_exec(self, command, args=None):
        return self.cloud.run("host.exec", actor=self.actor, host="test", command=command, args=args or [])

    def test_allowlisted_bare_command_runs(self):
        result = self.run_exec("uptime")
        self.assertTrue(result.ok, result.error)
        self.assertTrue(result.result["ok"])

    def test_allowlisted_subcommand_runs(self):
        result = self.run_exec("git", ["status"])
        self.assertTrue(result.ok, result.error)

    def test_command_outside_allowlist_is_rejected(self):
        result = self.run_exec("rm", ["-rf", "/"])
        self.assertFalse(result.ok)
        self.assertIn("not in the diagnostic exec allowlist", result.error.message)

    def test_disallowed_subcommand_is_rejected(self):
        result = self.run_exec("systemctl", ["restart", "ssh"])
        self.assertFalse(result.ok)
        self.assertIn("requires its first argument to be one of", result.error.message)

    def test_command_with_no_subcommand_restriction_needs_no_args(self):
        result = self.run_exec("uname")
        self.assertTrue(result.ok, result.error)

    def test_shell_metacharacters_in_args_are_not_interpreted(self):
        # argv-based transport: this must be passed to `cat` as a single literal
        # filename argument, never parsed by a shell -- so it correctly fails as
        # "no such file", not as a successful injected command.
        result = self.run_exec("cat", ["/nonexistent; echo pwned"])
        self.assertTrue(result.ok)  # the action itself runs
        self.assertNotEqual(result.result["exit_code"], 0)  # but the "command" fails as a bad path
        self.assertNotIn("pwned", result.result["stdout"])

    def test_action_is_read_only_and_requires_no_confirmation(self):
        action = self.cloud.actions.get("host.exec")
        self.assertTrue(action.read_only)
        self.assertFalse(action.destructive)
        self.assertEqual(action.confirmation, "none")


if __name__ == "__main__":
    unittest.main()
