# SPDX-License-Identifier: MPL-2.0
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from apx import APX
from apx.protocol import MCPServer, tool_name


def create_test_config(tmp_path: Path) -> Path:
    path = tmp_path / "apx.toml"
    path.write_text("""version = 1

[[hosts]]
name = "local"
transport = "local"

[[projects]]
name = "test-project"
description = "Test Project Description"
""")
    return path


class MCPInteropTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.config_path = create_test_config(Path(self.temp_dir.name))
        self.cloud = APX(self.config_path, plugins=False)
        self.server = MCPServer(self.cloud, actor="human:operator")

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_tool_name_conversion(self):
        self.assertEqual(tool_name("host.inspect"), "host_info")
        self.assertEqual(tool_name("project.list"), "project_list")
        self.assertEqual(tool_name("service.status"), "service_status")

    def test_initialize_endpoint(self):
        req = {
            "jsonrpc": "2.0",
            "id": "init-1",
            "method": "initialize",
            "params": {
                "protocolVersion": "2024-11-05",
                "clientInfo": {"name": "test-client", "version": "1.0.0"}
            }
        }
        res = self.server.dispatch(req)
        self.assertEqual(res["jsonrpc"], "2.0")
        self.assertEqual(res["id"], "init-1")
        self.assertIn("result", res)
        result = res["result"]
        self.assertEqual(result["protocolVersion"], "2024-11-05")
        self.assertEqual(result["serverInfo"]["name"], "apx")
        self.assertIn("tools", result["capabilities"])

    def test_ping_endpoint(self):
        req = {"jsonrpc": "2.0", "id": "ping-1", "method": "ping"}
        res = self.server.dispatch(req)
        self.assertEqual(res["jsonrpc"], "2.0")
        self.assertEqual(res["id"], "ping-1")
        self.assertEqual(res["result"], {})

    def test_tools_list_endpoint(self):
        req = {"jsonrpc": "2.0", "id": "list-1", "method": "tools/list"}
        res = self.server.dispatch(req)
        self.assertEqual(res["jsonrpc"], "2.0")
        self.assertEqual(res["id"], "list-1")
        tools = res["result"]["tools"]
        self.assertIsInstance(tools, list)
        self.assertGreater(len(tools), 5)
        
        tool_names = {t["name"] for t in tools}
        self.assertIn("host_info", tool_names)
        self.assertIn("project_list", tool_names)
        self.assertIn("state_show", tool_names)

        # Verify tool schema details
        project_list_tool = next(t for t in tools if t["name"] == "project_list")
        self.assertEqual(project_list_tool["title"], "project.list")
        self.assertIn("inputSchema", project_list_tool)
        self.assertIn("annotations", project_list_tool)

    def test_tools_call_success(self):
        req = {
            "jsonrpc": "2.0",
            "id": "call-1",
            "method": "tools/call",
            "params": {
                "name": "project_list",
                "arguments": {}
            }
        }
        res = self.server.dispatch(req)
        self.assertEqual(res["jsonrpc"], "2.0")
        self.assertEqual(res["id"], "call-1")
        self.assertFalse(res["result"]["isError"])
        structured = res["result"]["structuredContent"]
        self.assertTrue(structured["ok"])
        self.assertEqual(len(structured["result"]["projects"]), 1)
        self.assertEqual(structured["result"]["projects"][0]["name"], "test-project")

    def test_tools_call_destructive_requires_confirm(self):
        req = {
            "jsonrpc": "2.0",
            "id": "call-dest-1",
            "method": "tools/call",
            "params": {
                "name": "host_shutdown",
                "arguments": {"host": "local"}
            }
        }
        res = self.server.dispatch(req)
        self.assertIn("error", res)
        self.assertIn("confirm=true", res["error"]["message"])

    def test_tools_call_unknown_tool(self):
        req = {
            "jsonrpc": "2.0",
            "id": "call-unknown",
            "method": "tools/call",
            "params": {
                "name": "non_existent_tool_xyz",
                "arguments": {}
            }
        }
        res = self.server.dispatch(req)
        self.assertEqual(res["error"]["code"], -32602)
        self.assertIn("unknown tool", res["error"]["message"])

    def test_unknown_method(self):
        req = {
            "jsonrpc": "2.0",
            "id": "unknown-meth",
            "method": "unsupported/method"
        }
        res = self.server.dispatch(req)
        self.assertEqual(res["error"]["code"], -32601)

    def test_notification_returns_none(self):
        req = {"jsonrpc": "2.0", "method": "notifications/initialized"}
        res = self.server.dispatch(req)
        self.assertIsNone(res)

    def test_serve_stdio_roundtrip(self):
        messages = [
            json.dumps({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}}),
            json.dumps({"jsonrpc": "2.0", "id": 2, "method": "tools/call", "params": {"name": "project_list", "arguments": {}}}),
        ]
        input_stream = io.StringIO("\n".join(messages) + "\n")
        output_stream = io.StringIO()

        with patch("sys.stdin", input_stream), patch("sys.stdout", output_stream):
            code = self.server.serve()
            self.assertEqual(code, 0)

        lines = output_stream.getvalue().strip().splitlines()
        self.assertEqual(len(lines), 2)
        res1 = json.loads(lines[0])
        res2 = json.loads(lines[1])
        self.assertEqual(res1["id"], 1)
        self.assertEqual(res2["id"], 2)
        self.assertTrue(res2["result"]["structuredContent"]["ok"])


if __name__ == "__main__":
    unittest.main()
