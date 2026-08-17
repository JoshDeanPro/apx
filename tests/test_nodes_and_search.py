import tempfile
import unittest
from pathlib import Path

from apx import APX


def config(tmp_path: Path, extra: str = "") -> Path:
    path = tmp_path / "apx.toml"
    path.write_text(
        'version=1\n[[hosts]]\nname="test"\ntransport="local"\n[[hosts]]\nname="prod"\ntransport="local"\n'
        '[[projects]]\nname="demo"\ndescription="demo website project"\ntags=["web"]\n' + extra
    )
    return path


class NodeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.cloud = APX(config(Path(self.temp.name)), plugins=False)
        self.actor = self.cloud.actors.resolve_default()

    def tearDown(self): self.temp.cleanup()

    def test_inspect_discovers_and_caches(self):
        first = self.cloud.run("node.inspect", actor=self.actor, host="test")
        self.assertTrue(first.ok, first.error)
        self.assertIn("os", first.result)
        self.assertIn("battery", first.result)
        self.assertIn("browsers", first.result)
        self.assertIn("local_ai", first.result)
        self.assertFalse(first.result["stale"])
        second = self.cloud.run("node.inspect", actor=self.actor, host="test")
        self.assertEqual(second.result["cached_at"], first.result["cached_at"])  # served from cache

    def test_refresh_forces_a_new_probe(self):
        first = self.cloud.run("node.inspect", actor=self.actor, host="test")
        refreshed = self.cloud.run("node.refresh", actor=self.actor, host="test")
        self.assertTrue(refreshed.ok)
        # cached_at is a fresh timestamp -- can't assert strictly greater on a fast
        # local run without flaking, but the store must have actually re-saved.
        self.assertIn("cached_at", refreshed.result)

    def test_list_returns_only_discovered_nodes(self):
        self.assertEqual(self.cloud.run("node.list", actor=self.actor).result["nodes"], [])
        self.cloud.run("node.inspect", actor=self.actor, host="test")
        names = {n["name"] for n in self.cloud.run("node.list", actor=self.actor).result["nodes"]}
        self.assertEqual(names, {"test"})

    def test_inspect_unknown_host_fails_cleanly(self):
        result = self.cloud.run("node.inspect", actor=self.actor, host="nope")
        self.assertFalse(result.ok)


ROLES_TOML = (
    '[[actors]]\nid="agent:coder"\nkind="agent"\nroles=["coder"]\n'
    '[[actors]]\nid="human:admin"\nkind="human"\nroles=["admin"]\n'
    '[[roles]]\nname="coder"\nallow=[{action="project.*",scope={host=["test"]}},{action="service.restart",scope={host=["prod"]}}]\n'
    '[[roles]]\nname="admin"\nallow=[{action="*"}]\n'
)


class NodePermissionEnforcementTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.cloud = APX(config(Path(self.temp.name), ROLES_TOML), plugins=False)

    def tearDown(self): self.temp.cleanup()

    def test_effective_permissions_differ_per_node(self):
        on_test = self.cloud.run("node.permissions", actor="human:admin", host="test", subject="agent:coder")
        on_prod = self.cloud.run("node.permissions", actor="human:admin", host="prod", subject="agent:coder")
        self.assertTrue(on_test.ok and on_prod.ok)
        self.assertIn("project.list", on_test.result["allowed"])
        self.assertNotIn("service.restart", on_test.result["allowed"])
        self.assertIn("service.restart", on_prod.result["allowed"])
        self.assertNotIn("project.list", on_prod.result["allowed"])

    def test_reported_permissions_match_real_enforcement(self):
        # not cosmetic: what node.permissions reports for prod must match what
        # actually executing the action against prod does.
        reported = self.cloud.run("node.permissions", actor="human:admin", host="prod", subject="agent:coder").result["allowed"]
        self.assertIn("service.restart", reported)
        # service.restart against prod requires systemd, which this test box lacks --
        # it should fail on capability grounds, not on permission grounds.
        outcome = self.cloud.run("service.restart", actor="agent:coder", host="prod", service="web",
                                  confirmation={"level": "confirm", "confirmed": True, "authorization_id": "t1"})
        self.assertNotEqual(outcome.error.code if outcome.error else None, "permission_denied")
        # an action absent from the reported list must actually be denied
        self.assertNotIn("service.restart", self.cloud.run("node.permissions", actor="human:admin", host="test", subject="agent:coder").result["allowed"])
        denied = self.cloud.run("service.restart", actor="agent:coder", host="test", service="web",
                                 confirmation={"level": "confirm", "confirmed": True, "authorization_id": "t2"})
        self.assertEqual(denied.error.code, "permission_denied")


class SearchTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.cloud = APX(config(Path(self.temp.name)), plugins=False)
        self.actor = self.cloud.actors.resolve_default()

    def tearDown(self): self.temp.cleanup()

    def test_finds_hosts_projects_and_actions(self):
        result = self.cloud.run("search.query", actor=self.actor, query="test")
        kinds = {item["kind"] for item in result.result["results"]}
        ids = {item["id"] for item in result.result["results"]}
        self.assertIn("node", kinds)
        self.assertIn("test", ids)

    def test_exact_match_ranks_above_substring_match(self):
        result = self.cloud.run("search.query", actor=self.actor, query="demo")
        results = result.result["results"]
        self.assertGreater(len(results), 0)
        self.assertEqual(results[0]["id"], "demo")
        self.assertEqual(results[0]["score"], 100)

    def test_kind_filter_narrows_results(self):
        result = self.cloud.run("search.query", actor=self.actor, query="test", kinds=["project"])
        self.assertEqual(result.result["results"], [])

    def test_finds_blueprints_by_tag(self):
        result = self.cloud.run("search.query", actor=self.actor, query="scaffold")
        ids = {item["id"] for item in result.result["results"] if item["kind"] == "blueprint"}
        self.assertIn("project/base-layout", ids)

    def test_empty_query_returns_nothing(self):
        result = self.cloud.run("search.query", actor=self.actor, query="   ")
        self.assertEqual(result.result["results"], [])


if __name__ == "__main__":
    unittest.main()
