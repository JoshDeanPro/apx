import tempfile
import unittest
from pathlib import Path
from unittest import mock

from apx.agent_install import PLANNED_AGENTS, install


class AgentInstallTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)

    def tearDown(self): self.temp.cleanup()

    def test__code_project_scope_writes_slash_command_and_skill_no_mcp(self):
        result = install("-code", root=self.root)
        self.assertEqual(result["scope"], "project")
        command_path = self.root/"./commands/apx.md"
        skill_path = self.root/"./skills/apx/SKILL.md"
        self.assertTrue(command_path.exists())
        self.assertTrue(skill_path.exists())
        self.assertFalse((self.root/".mcp.json").exists())  # no MCP involved at all
        self.assertIn("apx $ARGUMENTS", command_path.read_text())
        self.assertNotIn("mcpServers", command_path.read_text())
        self.assertNotIn("mcp server", skill_path.read_text().lower())

    def test_global_scope_writes_under_home_not_project(self):
        with tempfile.TemporaryDirectory() as fake_home:
            with mock.patch("pathlib.Path.home", return_value=Path(fake_home)):
                result = install("-code", root=self.root, global_scope=True)
            self.assertEqual(result["scope"], "user")
            self.assertFalse((self.root/".").exists())
            self.assertTrue((Path(fake_home)/"./commands/apx.md").exists())
            self.assertTrue((Path(fake_home)/"./skills/apx/SKILL.md").exists())

    def test_codex_writes_only_a_skill_no_slash_command_no_mcp(self):
        with tempfile.TemporaryDirectory() as fake_home:
            with mock.patch("pathlib.Path.home", return_value=Path(fake_home)):
                result = install("codex", root=self.root)
            self.assertEqual(result["scope"], "user")
            skill_path = Path(fake_home)/".codex/skills/apx/SKILL.md"
            self.assertTrue(skill_path.exists())
            self.assertEqual(result["written"], [str(skill_path)])
            self.assertFalse((Path(fake_home)/".codex/commands").exists())
            self.assertNotIn("mcp server", skill_path.read_text().lower())

    def test_codex_skill_uses_the_same_verified_frontmatter_shape(self):
        with tempfile.TemporaryDirectory() as fake_home:
            with mock.patch("pathlib.Path.home", return_value=Path(fake_home)):
                install("codex", root=self.root)
            content = (Path(fake_home)/".codex/skills/apx/SKILL.md").read_text()
        self.assertTrue(content.startswith("---\nname: apx\ndescription:"))

    def test_planned_agents_are_reported_as_planned_not_fabricated(self):
        for agent in PLANNED_AGENTS:
            result = install(agent, root=self.root)
            self.assertEqual(result["status"], "planned")
            self.assertEqual(result["written"], [])

    def test_unknown_agent_raises(self):
        with self.assertRaises(ValueError):
            install("no-such-agent", root=self.root)


if __name__ == "__main__":
    unittest.main()
