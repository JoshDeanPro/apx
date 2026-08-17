import tempfile
import unittest
from pathlib import Path

from apx import APX
from apx.protocol import MCPServer


def config(tmp_path: Path, extra: str = "") -> Path:
    path = tmp_path / "apx.toml"
    path.write_text('version=1\n[[hosts]]\nname="test"\ntransport="local"\n[[projects]]\nname="demo"\ndescription="demo"\n' + extra)
    return path


ROLES_TOML = (
    '[[actors]]\nid="human:admin"\nkind="human"\nroles=["payroll_admin"]\n'
    '[[actors]]\nid="human:employee"\nkind="human"\nroles=["employee"]\n'
    '[[roles]]\nname="payroll_admin"\nallow=[{action="discovery.capabilities"},{action="actor.whoami"},{action="blueprint.*"},{action="grant.*"}]\n'
    '[[roles]]\nname="employee"\nallow=[{action="discovery.capabilities"},{action="actor.whoami"}]\n'
)


class DiscoveryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.cloud = APX(config(Path(self.temp.name), ROLES_TOML), plugins=False)

    def tearDown(self): self.temp.cleanup()

    def test_unconfigured_default_actor_sees_everything(self):
        # no [[roles]] apply to the plain, unconfigured setup -- policy is a no-op,
        # so discovery should be the full registered action list.
        cloud = APX(config(Path(self.temp.name)), plugins=False)
        result = cloud.run("discovery.capabilities", actor=cloud.actors.resolve_default())
        self.assertTrue(result.ok)
        self.assertEqual(len(result.result["capabilities"]), len(cloud.actions.list()))

    def test_discovery_is_filtered_per_subject(self):
        admin_view = self.cloud.run("discovery.capabilities", actor="human:admin", subject="human:admin")
        employee_view = self.cloud.run("discovery.capabilities", actor="human:employee", subject="human:employee")
        admin_ids = {c["id"] for c in admin_view.result["capabilities"]}
        employee_ids = {c["id"] for c in employee_view.result["capabilities"]}
        self.assertIn("blueprint.apply", admin_ids)
        self.assertNotIn("blueprint.apply", employee_ids)
        self.assertLess(employee_ids, admin_ids)  # strict subset

    def test_introspection_actions_are_always_discoverable(self):
        result = self.cloud.run("discovery.capabilities", actor="human:employee", subject="human:employee")
        ids = {c["id"] for c in result.result["capabilities"]}
        self.assertIn("discovery.capabilities", ids)
        self.assertIn("actor.whoami", ids)

    def test_manual_invocation_of_undiscovered_action_is_still_denied(self):
        # defense in depth: even if a caller somehow knows the action name, invoking
        # what discovery would never have surfaced must still fail policy.
        result = self.cloud.run("blueprint.apply", actor="human:employee", blueprint="project/base-layout")
        self.assertFalse(result.ok)
        self.assertEqual(result.error.code, "permission_denied")

    def test_capability_graph_actor_filter_matches_discover(self):
        unfiltered = self.cloud.capability_graph()
        filtered = self.cloud.capability_graph("human:employee")
        self.assertLess(len(filtered.actions), len(unfiltered.actions))
        self.assertIn("actor.whoami", filtered.actions)
        self.assertNotIn("blueprint.apply", filtered.actions)

    def test_mcp_tool_listing_matches_discovery_filtering(self):
        server = MCPServer(self.cloud, actor="human:employee")
        tool_names = {tool["title"] for tool in server.tools()}
        discovered = self.cloud.run("discovery.capabilities", actor="human:employee", subject="human:employee")
        discovered_ids = {c["id"] for c in discovered.result["capabilities"]}
        self.assertEqual(tool_names, discovered_ids)

    def test_grant_is_visible_in_mcp_tool_listing_immediately(self):
        server_before = MCPServer(self.cloud, actor="human:employee")
        self.assertNotIn("blueprint.list", {t["title"] for t in server_before.tools()})
        self.cloud.run("grant.issue", actor="human:admin", subject="human:employee", actions=["blueprint.list"])
        server_after = MCPServer(self.cloud, actor="human:employee")
        self.assertIn("blueprint.list", {t["title"] for t in server_after.tools()})


if __name__ == "__main__":
    unittest.main()
