import os
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from apx import selfupdate


def _git(args: list[str], cwd: Path) -> None:
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True,
                    env={"GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t", "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t", "PATH": "/usr/bin:/bin"})


def _make_repo(root: Path, *, with_upstream: bool = False) -> Path | None:
    _git(["init", "-q"], root)
    _git(["checkout", "-q", "-b", "main"], root)
    (root/"pyproject.toml").write_text("[project]\nname='x'\n")
    _git(["add", "."], root)
    _git(["commit", "-q", "-m", "init"], root)
    if not with_upstream: return None
    remote = root.parent/"remote.git"
    subprocess.run(["git", "init", "-q", "--bare", str(remote)], check=True, capture_output=True)
    _git(["remote", "add", "origin", str(remote)], root)
    _git(["push", "-q", "-u", "origin", "main"], root)
    return remote


class SelfUpdateTests(unittest.TestCase):
    def _repo(self) -> Path:
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        root = Path(temp.name)/"repo"
        root.mkdir()
        return root

    def _patched_root(self, root: Path):
        return mock.patch.object(selfupdate, "_repo_root", return_value=root)

    def test_version_info_on_a_plain_repo(self):
        root = self._repo(); _make_repo(root)
        with self._patched_root(root):
            info = selfupdate.version_info()
        self.assertEqual(info["git"]["branch"], "main")
        self.assertIsNotNone(info["git"]["commit"])
        self.assertFalse(info["git"]["dirty"])

    def test_version_info_detects_dirty_tree(self):
        root = self._repo(); _make_repo(root)
        (root/"pyproject.toml").write_text("changed")
        with self._patched_root(root):
            info = selfupdate.version_info()
        self.assertTrue(info["git"]["dirty"])

    def test_check_for_updates_without_upstream_reports_no_update(self):
        root = self._repo(); _make_repo(root)
        with self._patched_root(root):
            result = selfupdate.check_for_updates()
        self.assertEqual(result["kind"], "development")
        self.assertFalse(result["update_available"])
        self.assertIn("error", result)

    def test_check_for_updates_with_real_upstream_ahead(self):
        root = self._repo(); remote = _make_repo(root, with_upstream=True)
        clone = root.parent/"clone"
        subprocess.run(["git", "clone", "-q", str(remote), str(clone)], check=True, capture_output=True)
        _git(["checkout", "-q", "main"], clone)  # the bare remote's default HEAD may not be "main"
        (clone/"new.txt").write_text("x")
        _git(["add", "."], clone); _git(["commit", "-q", "-m", "second"], clone); _git(["push", "-q"], clone)
        with self._patched_root(root):
            result = selfupdate.check_for_updates()
        self.assertTrue(result["update_available"])
        self.assertEqual(result["commits_behind"], 1)

    def test_apply_update_refuses_with_uncommitted_changes(self):
        root = self._repo(); _make_repo(root, with_upstream=True)
        (root/"pyproject.toml").write_text("dirty")
        with self._patched_root(root):
            with self.assertRaises(selfupdate.UpdateError):
                selfupdate.apply_update()

    def test_apply_update_fast_forwards_and_skips_reinstall_when_deps_unchanged(self):
        root = self._repo(); remote = _make_repo(root, with_upstream=True)
        clone = root.parent/"clone"
        subprocess.run(["git", "clone", "-q", str(remote), str(clone)], check=True, capture_output=True)
        _git(["checkout", "-q", "main"], clone)  # the bare remote's default HEAD may not be "main"
        (clone/"README.md").write_text("docs only, pyproject.toml untouched")
        _git(["add", "."], clone); _git(["commit", "-q", "-m", "docs"], clone); _git(["push", "-q"], clone)
        with self._patched_root(root):
            result = selfupdate.apply_update()
        self.assertTrue(result["updated"])
        self.assertFalse(result["reinstalled"])
        self.assertTrue((root/"README.md").exists())

    def test_apply_update_on_non_git_directory_raises(self):
        root = self._repo(); root.mkdir(exist_ok=True)
        with self._patched_root(root):
            with self.assertRaises(selfupdate.UpdateError):
                selfupdate.apply_update()


class InstalledRuntimeTests(unittest.TestCase):
    """An installed runtime is not a checkout, and updating it must not depend on
    any hosted service knowing it exists."""

    def _installed(self):
        return mock.patch.object(selfupdate, "_is_development_checkout", return_value=False)

    def _no_source_in_environment(self):
        environment = {k: v for k, v in os.environ.items() if k != "APX_UPDATE_SOURCE"}
        return mock.patch.dict("os.environ", environment, clear=True)

    def test_update_without_a_configured_source_says_so_instead_of_reaching_out(self):
        with self._installed(), self._no_source_in_environment():
            with self.assertRaises(selfupdate.UpdateError) as caught:
                selfupdate.apply_update()
        self.assertIn("no update source configured", str(caught.exception))

    def test_check_reports_the_configured_source_and_never_fetches(self):
        with self._installed():
            result = selfupdate.check_for_updates(config={"update": {"source": "/srv/wheels/apx.whl"}})
        self.assertEqual(result["kind"], "installed")
        self.assertEqual(result["source"], "/srv/wheels/apx.whl")

    def test_source_precedence_is_explicit_then_environment_then_config(self):
        config = {"update": {"source": "from-config"}}
        with mock.patch.dict("os.environ", {"APX_UPDATE_SOURCE": "from-environment"}):
            self.assertEqual(selfupdate.update_source("from-flag", config), "from-flag")
            self.assertEqual(selfupdate.update_source(None, config), "from-environment")
        with self._no_source_in_environment():
            self.assertEqual(selfupdate.update_source(None, config), "from-config")

    def test_update_installs_the_configured_source_with_pip(self):
        calls = []

        def fake_run(argv, cwd=None, timeout=30):
            calls.append(argv)
            if "importlib.metadata" in " ".join(argv): return True, "9.9.9", ""
            return True, "", ""

        with self._installed(), mock.patch.object(selfupdate, "_run", fake_run):
            result = selfupdate.apply_update(config={"update": {"source": "/srv/wheels/apx.whl"}})
        self.assertEqual(result["kind"], "installed")
        self.assertEqual(result["after"], "9.9.9")
        self.assertIn(["--upgrade", "/srv/wheels/apx.whl"], [argv[-2:] for argv in calls])

    def test_pushing_to_the_local_node_is_refused(self):
        from apx.models import Host
        with self.assertRaises(selfupdate.UpdateError):
            selfupdate.push_to_host(Host("mac", "local", is_self=True))


if __name__ == "__main__":
    unittest.main()
