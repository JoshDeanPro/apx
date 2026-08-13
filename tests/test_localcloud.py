import tempfile
import unittest
from pathlib import Path

from localcloud import LocalCloud
from localcloud.protocol import MCPServer


def config(tmp_path: Path) -> Path:
    path=tmp_path/"localcloud.toml"
    path.write_text('version=1\n[[hosts]]\nname="test"\ntransport="local"\n')
    return path


class LocalCloudTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.cloud=LocalCloud(config(Path(self.temp.name)),plugins=False)

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


if __name__ == "__main__": unittest.main()
