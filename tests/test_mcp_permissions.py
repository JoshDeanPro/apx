import tempfile
import unittest
from pathlib import Path

from apx import APX
from apx.protocol import MCPServer
from apx.examples.subscriptions import build_reference_provider


def config(tmp_path: Path, extra: str = "") -> Path:
    path=tmp_path/"apx.toml"
    path.write_text('version=1\n[[hosts]]\nname="mac"\ntransport="local"\n[[hosts]]\nname="vps"\ntransport="local"\n[[projects]]\nname="palisbot"\n'+extra)
    return path


ROLES = '''
[[actors]]
id="agent::mac"
roles=["developer"]
[[actors]]
id="agent::vps"
roles=["developer","deployer"]
[[roles]]
name="developer"
[[roles.allow]]
action="project.inspect"
[[roles.allow]]
action="service.status"
[[roles]]
name="deployer"
[[roles.allow]]
action="service.restart"
scope={project=["palisbot"]}
'''


class MCPPermissionTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.cloud=APX(config(Path(self.temp.name),ROLES),plugins=False)

    def tearDown(self): self.temp.cleanup()

    def test_tool_listing_is_filtered_per_actor(self):
        mac_tools={t["name"] for t in MCPServer(self.cloud,actor="agent::mac").tools()}
        vps_tools={t["name"] for t in MCPServer(self.cloud,actor="agent::vps").tools()}
        self.assertNotIn("service_restart",mac_tools)
        self.assertIn("service_restart",vps_tools)
        self.assertIn("service_status",mac_tools)

    def test_authoritative_enforcement_even_if_tool_were_listed(self):
        # dispatch-time enforcement must hold even for a tool that a stale/bypassed
        # listing might have shown -- the pre-filter in tools() is convenience only.
        server=MCPServer(self.cloud,actor="agent::mac")
        request={"jsonrpc":"2.0","id":1,"method":"tools/call","params":{"name":"service_restart","arguments":{"host":"vps","service":"x","confirm":True}}}
        response=server.dispatch(request)
        self.assertTrue(response["result"]["isError"])
        self.assertEqual(response["result"]["structuredContent"]["error"]["code"],"permission_denied")

    def test_deployer_allowed_end_to_end_through_mcp(self):
        server=MCPServer(self.cloud,actor="agent::vps")
        request={"jsonrpc":"2.0","id":1,"method":"tools/call","params":{"name":"service_status","arguments":{"host":"vps","service":"x"}}}
        response=server.dispatch(request)
        # service.status itself will fail (no real systemd unit "x"), but it must NOT be a permission_denied.
        self.assertNotEqual(response["result"]["structuredContent"].get("error",{}).get("code"),"permission_denied")

    def test_unconfigured_actor_defaults_to_open_listing_when_policy_disabled(self):
        open_cloud=APX(config(Path(self.temp.name),""),plugins=False)
        tools={t["name"] for t in MCPServer(open_cloud).tools()}
        self.assertIn("service_restart",tools)

    def test_provider_mutation_uses_prepare_and_bound_confirmation(self):
        cloud=APX(config(Path(self.temp.name),""),plugins=False); cloud.register_provider(build_reference_provider())
        server=MCPServer(cloud,actor="agent:mcp",auth_context={"principal_id":"agent:mcp"})
        first=server.dispatch({"jsonrpc":"2.0","id":1,"method":"tools/call","params":{"name":"subscription_resume","arguments":{}}})
        prepared=first["result"]["structuredContent"]; self.assertEqual(prepared["status"],"prepared")
        arguments={"prepared_action_id":prepared["prepared_action_id"],"idempotency_key":"mcp-resume",
            "authoritative_state_version":prepared["authoritative_state_version"],"confirmation":{"level":"confirm","confirmed":True,"authorization_id":"mcp-confirm"}}
        second=server.dispatch({"jsonrpc":"2.0","id":2,"method":"tools/call","params":{"name":"subscription_resume","arguments":arguments}})
        self.assertEqual(second["result"]["structuredContent"]["status"],"completed")


if __name__ == "__main__": unittest.main()
