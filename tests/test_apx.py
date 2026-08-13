import tempfile
import unittest
from pathlib import Path

from apx import APX
from apx.protocol import MCPServer


def config(tmp_path: Path) -> Path:
    path=tmp_path/"apx.toml"
    path.write_text('version=1\n[[hosts]]\nname="test"\ntransport="local"\n')
    return path


class APXTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.cloud=APX(config(Path(self.temp.name)),plugins=False)

    def tearDown(self): self.temp.cleanup()

    def test_python_and_discovery_share_action(self):
        result=self.cloud.run("host.info",host="test")
        self.assertTrue(result.ok)
        self.assertEqual(result.data["name"],"test")
        self.assertTrue(result.data["capabilities"]["python"]["available"])

    def test_mcp_lists_shared_actions(self):
        server=MCPServer(self.cloud)
        names={tool["name"] for tool in server.tools()}
        self.assertLessEqual({"host_info","service_status","file_copy","project_inspect"},names)
        request={"jsonrpc":"2.0","id":1,"method":"tools/call","params":{"name":"host_info","arguments":{"host":"test"}}}
        self.assertTrue(server.dispatch(request)["result"]["structuredContent"]["ok"])

    def test_destructive_mcp_requires_confirmation(self):
        server=MCPServer(self.cloud)
        request={"jsonrpc":"2.0","id":1,"method":"tools/call","params":{"name":"host_shutdown","arguments":{"host":"test"}}}
        self.assertIn("confirm=true",server.dispatch(request)["error"]["message"])

    def test_actor_threads_identically_through_python_and_mcp(self):
        python_result=self.cloud.run("actor.whoami",subject="agent::mac")
        server=MCPServer(self.cloud,actor="agent::mac")
        request={"jsonrpc":"2.0","id":1,"method":"tools/call","params":{"name":"actor_whoami","arguments":{"subject":"agent::mac"}}}
        mcp_result=server.dispatch(request)["result"]["structuredContent"]
        self.assertEqual(python_result.result["actor"],mcp_result["result"]["actor"])
        self.assertEqual(python_result.result["actor"],"agent::mac")

    def test_unconfigured_default_actor_is_open_for_every_caller(self):
        # No [[roles]] declared -- CLI, Python, and MCP must all remain unrestricted.
        self.assertTrue(self.cloud.run("host.info",host="test").ok)
        self.assertTrue(self.cloud.run("host.info",host="test",actor="agent::anything").ok)

    def test_unexpected_input_field_fails_cleanly_instead_of_crashing(self):
        # A mismatched/misspelled action input is a caller mistake, not a process crash --
        # this must be true for every action, at the one shared execution point.
        result=self.cloud.run("host.info",host="test",bogus_extra_field="oops")
        self.assertFalse(result.ok)
        self.assertEqual(result.error.code,"invalid_input")
        self.assertIn("bogus_extra_field",result.error.message)


if __name__ == "__main__": unittest.main()
