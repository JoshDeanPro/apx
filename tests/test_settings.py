# SPDX-License-Identifier: MPL-2.0
import io
import json
import tempfile
import unittest
from pathlib import Path

from apx import cli, settings


class SettingsTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        self.home = Path(self.temp_dir.name) / ".config" / "apx"
        self.home.mkdir(parents=True, exist_ok=True)
        self.config_path = self.home / "config.toml"
        self.config_path.write_text("""
[node]
name = "test-node"

[settings]
custom_flag = true
""")

    def test_get_all_settings(self):
        data = settings.get_all_settings(self.config_path)
        self.assertEqual(data["node"]["name"], "test-node")
        self.assertEqual(data["node"]["default_actor"], "human:operator")
        self.assertTrue(data["paths"]["config_exists"])

    def test_format_settings(self):
        data = settings.get_all_settings(self.config_path)
        formatted = settings.format_settings(data)
        self.assertIn("APX Settings & Environment", formatted)
        self.assertIn("test-node", formatted)
        self.assertIn("apx settings get", formatted)
        self.assertIn("apx settings set", formatted)

    def test_get_setting(self):
        self.assertEqual(settings.get_setting("node.name", self.config_path), "test-node")
        self.assertEqual(settings.get_setting("settings.custom_flag", self.config_path), True)
        self.assertIsNone(settings.get_setting("nonexistent.key", self.config_path))

    def test_set_setting_existing_and_new(self):
        # Update existing key
        res = settings.set_setting("node.name", "renamed-node", self.config_path)
        self.assertTrue(res["ok"])
        self.assertEqual(settings.get_setting("node.name", self.config_path), "renamed-node")

        # Set new key
        res = settings.set_setting("settings.custom_flag", "false", self.config_path)
        self.assertTrue(res["ok"])
        self.assertEqual(settings.get_setting("settings.custom_flag", self.config_path), False)

    def test_cli_settings_command(self):
        # Test `apx settings show`
        code = cli.main(["--config", str(self.config_path), "settings", "show"])
        self.assertEqual(code, 0)

        # Test `apx settings get`
        code = cli.main(["--config", str(self.config_path), "settings", "get", "node.name"])
        self.assertEqual(code, 0)

        # Test `apx settings set`
        code = cli.main(["--config", str(self.config_path), "settings", "set", "node.name", "cli-node"])
        self.assertEqual(code, 0)
        self.assertEqual(settings.get_setting("node.name", self.config_path), "cli-node")


if __name__ == "__main__":
    unittest.main()

