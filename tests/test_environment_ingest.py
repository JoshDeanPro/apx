import json
import tempfile
import unittest
from pathlib import Path

from apx import APX
from apx.environment_ingest import CodeSource, CodexSource, PLANNED_SOURCES, SOURCES


def config(tmp_path: Path, extra: str = "") -> Path:
    path = tmp_path / "apx.toml"
    path.write_text('version=1\n[[hosts]]\nname="test"\ntransport="local"\n[[projects]]\nname="demo"\ndescription="demo"\n' + extra)
    return path


class SourceParsingTests(unittest.TestCase):
    def test__code_source_missing_file(self):
        source = CodeSource(Path("/nonexistent/..json"))
        self.assertEqual(source.probe(), {"id": "_code", "found": False})
        self.assertEqual(source.mcp_servers(), {})

    def test__code_source_parses_real_shape(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "..json"
            path.write_text(json.dumps({"mcpServers": {
                "main-mcp": {"type": "stdio", "command": "python3", "args": ["/x/main.py"], "env": {}},
                "http-one": {"type": "http", "url": "https://example.com"},  # non-stdio, must be excluded
            }}))
            source = CodeSource(path)
            probe = source.probe()
            self.assertTrue(probe["found"])
            self.assertEqual(probe["mcp_server_count"], 2)
            servers = source.mcp_servers()
            self.assertEqual(set(servers), {"main-mcp"})
            self.assertEqual(servers["main-mcp"]["command"], "python3")
            self.assertEqual(servers["main-mcp"]["args"], ["/x/main.py"])

    def test__code_source_handles_malformed_json(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "..json"
            path.write_text("{not valid")
            source = CodeSource(path)
            probe = source.probe()
            self.assertTrue(probe["found"])
            self.assertIn("error", probe)
            self.assertEqual(source.mcp_servers(), {})

    def test_codex_source_parses_real_shape(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "config.toml"
            path.write_text('[mcp_servers.codebase-memory]\ncommand = "/x/codebase-memory-mcp"\nargs = ["--tool-profile=analysis"]\n')
            source = CodexSource(path)
            probe = source.probe()
            self.assertTrue(probe["found"])
            self.assertEqual(probe["mcp_server_count"], 1)
            servers = source.mcp_servers()
            self.assertEqual(servers["codebase-memory"]["command"], "/x/codebase-memory-mcp")

    def test_codex_source_missing_file(self):
        source = CodexSource(Path("/nonexistent/config.toml"))
        self.assertEqual(source.probe(), {"id": "codex", "found": False})


class EnvironmentSourcesActionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.cloud = APX(config(Path(self.temp.name)), plugins=False)
        self.actor = self.cloud.actors.resolve_default()

    def tearDown(self): self.temp.cleanup()

    def test_sources_lists_every_known_and_planned_source(self):
        result = self.cloud.run("environment.sources", actor=self.actor)
        self.assertTrue(result.ok, result.error)
        ids = {s["id"] for s in result.result["sources"]}
        self.assertEqual(ids, set(SOURCES) | set(PLANNED_SOURCES))

    def test_sources_are_disabled_by_default(self):
        result = self.cloud.run("environment.sources", actor=self.actor)
        for entry in result.result["sources"]:
            if entry["id"] in SOURCES:
                self.assertFalse(entry["enabled"])

    def test_planned_sources_are_marked_planned_not_fabricated(self):
        result = self.cloud.run("environment.sources", actor=self.actor)
        for entry in result.result["sources"]:
            if entry["id"] in PLANNED_SOURCES:
                self.assertEqual(entry["status"], "planned")
                self.assertFalse(entry["verified"])

    def test_ingest_requires_confirmation(self):
        result = self.cloud.run("environment.ingest", actor=self.actor, source="_code")
        self.assertFalse(result.ok)
        self.assertEqual(result.status, "authorization_required")

    def test_ingest_refuses_a_disabled_source(self):
        result = self.cloud.run("environment.ingest", actor=self.actor,
                                 confirmation={"level": "confirm", "confirmed": True, "authorization_id": "t1"},
                                 source="_code")
        self.assertFalse(result.ok)
        self.assertIn("disabled", result.error.message)

    def test_ingest_refuses_a_planned_source(self):
        result = self.cloud.run("environment.ingest", actor=self.actor,
                                 confirmation={"level": "confirm", "confirmed": True, "authorization_id": "t2"},
                                 source="kimi_code")
        self.assertFalse(result.ok)
        self.assertIn("no verified ingestion support", result.error.message)

    def test_ingest_unknown_source_fails_cleanly(self):
        result = self.cloud.run("environment.ingest", actor=self.actor,
                                 confirmation={"level": "confirm", "confirmed": True, "authorization_id": "t3"},
                                 source="not-a-real-source")
        self.assertFalse(result.ok)


class EnvironmentIngestActionTests(unittest.TestCase):
    """Exercises the actual ingest path with a fake stdio MCP server (a tiny
    real subprocess), not the real ~/.codex or ~/..json -- proves the
    registration wiring works without depending on this machine's own state."""

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        server_script = Path(self.temp.name) / "fake_mcp_server.py"
        server_script.write_text(FAKE_MCP_SERVER)
        codex_config = Path(self.temp.name) / "config.toml"
        codex_config.write_text(f'[mcp_servers.fake]\ncommand = "{__import__("sys").executable}"\nargs = ["{server_script}"]\n')
        import apx.environment_ingest as module
        self._original_codex = module.SOURCES["codex"]
        module.SOURCES["codex"] = CodexSource(codex_config)
        self.cloud = APX(config(Path(self.temp.name), '[ingest.codex]\nenabled=true\n'), plugins=False)
        self.actor = self.cloud.actors.resolve_default()

    def tearDown(self):
        import apx.environment_ingest as module
        module.SOURCES["codex"] = self._original_codex
        self.temp.cleanup()

    def confirm(self, tag): return {"level": "confirm", "confirmed": True, "authorization_id": tag}

    def test_ingest_registers_the_servers_real_tools_as_apx_actions(self):
        result = self.cloud.run("environment.ingest", actor=self.actor, confirmation=self.confirm("i1"), source="codex")
        self.assertTrue(result.ok, result.error)
        self.assertEqual(result.result["ingested"][0]["connection"], "codex.fake")
        self.assertIn("codex.fake.echo", [a.name for a in self.cloud.actions.list()])

    def test_ingesting_twice_skips_already_ingested(self):
        self.cloud.run("environment.ingest", actor=self.actor, confirmation=self.confirm("i2"), source="codex")
        second = self.cloud.run("environment.ingest", actor=self.actor, confirmation=self.confirm("i3"), source="codex")
        self.assertTrue(second.ok)
        self.assertEqual(second.result["ingested"][0].get("skipped"), "already ingested")


FAKE_MCP_SERVER = '''
import json, sys

def send(msg):
    sys.stdout.write(json.dumps(msg) + "\\n"); sys.stdout.flush()

for line in sys.stdin:
    line = line.strip()
    if not line: continue
    request = json.loads(line)
    method = request.get("method")
    if method == "initialize":
        send({"jsonrpc": "2.0", "id": request["id"], "result": {"protocolVersion": "2025-06-18", "capabilities": {}, "serverInfo": {"name": "fake", "version": "0"}}})
    elif method == "notifications/initialized":
        pass
    elif method == "tools/list":
        send({"jsonrpc": "2.0", "id": request["id"], "result": {"tools": [{"name": "echo", "description": "echo back", "inputSchema": {"type": "object", "properties": {}}}]}})
    elif method == "tools/call":
        send({"jsonrpc": "2.0", "id": request["id"], "result": {"content": [{"type": "text", "text": "ok"}], "structuredContent": {"ok": True}}})
'''


if __name__ == "__main__":
    unittest.main()
