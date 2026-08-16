# SPDX-License-Identifier: MPL-2.0
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from apx import cli, selfupdate, settings


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
auto_update_check = true

[update]
source = "https://github.com/JoshDeanPro/apx.git"
""")

    def test_get_all_settings(self):
        data = settings.get_all_settings(self.config_path)
        self.assertEqual(data["node"]["name"], "test-node")
        self.assertEqual(data["update"]["source"], "https://github.com/JoshDeanPro/apx.git")
        self.assertTrue(data["update"]["auto_check"])
        self.assertTrue(data["paths"]["config_exists"])

    def test_format_settings(self):
        data = settings.get_all_settings(self.config_path)
        formatted = settings.format_settings(data)
        self.assertIn("APX Settings & Environment", formatted)
        self.assertIn("test-node", formatted)
        self.assertIn("apx settings doctor", formatted)
        self.assertIn("apx settings update", formatted)

    def test_get_setting(self):
        self.assertEqual(settings.get_setting("node.name", self.config_path), "test-node")
        self.assertEqual(settings.get_setting("settings.auto_update_check", self.config_path), True)
        self.assertEqual(settings.get_setting("update.source", self.config_path), "https://github.com/JoshDeanPro/apx.git")
        self.assertIsNone(settings.get_setting("nonexistent.key", self.config_path))

    def test_set_setting_existing_and_new(self):
        # Update existing key
        res = settings.set_setting("node.name", "renamed-node", self.config_path)
        self.assertTrue(res["ok"])
        self.assertEqual(settings.get_setting("node.name", self.config_path), "renamed-node")

        # Set new key
        res = settings.set_setting("settings.auto_update_check", "false", self.config_path)
        self.assertTrue(res["ok"])
        self.assertEqual(settings.get_setting("settings.auto_update_check", self.config_path), False)

    def test_auto_check_updates_caching(self):
        with mock.patch.object(selfupdate, "check_for_updates", return_value={"update_available": True, "commits_behind": 3, "upstream": "origin/main"}):
            with mock.patch.object(settings, "apx_home", return_value=self.home):
                with mock.patch.object(selfupdate, "_update_cache_path", return_value=self.home / "cache" / "update.json"):
                    # First run calls check_for_updates
                    res1 = selfupdate.auto_check_updates(ttl_seconds=3600)
                    self.assertTrue(res1["update_available"])
                    self.assertEqual(res1["commits_behind"], 3)

                    # Second run uses cache even if check_for_updates would return something else
                    with mock.patch.object(selfupdate, "check_for_updates", return_value={"update_available": False}):
                        res2 = selfupdate.auto_check_updates(ttl_seconds=3600)
                        self.assertTrue(res2["update_available"])

    def test_notify_if_update_available(self):
        stream = io.StringIO()
        stream.isatty = lambda: True
        with mock.patch.object(selfupdate, "auto_check_updates", return_value={"update_available": True, "commits_behind": 2, "upstream": "origin/main"}):
            notice = selfupdate.notify_if_update_available(stream=stream)
            self.assertIsNotNone(notice)
            self.assertIn("Update available: 2 new commits", notice)

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
