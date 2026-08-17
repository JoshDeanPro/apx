# SPDX-License-Identifier: MPL-2.0
import json
import os
import tempfile
import unittest
from pathlib import Path

from apx import APX
from apx.auth import AuthenticationError, AuthManager, LocalAuthProvider, Principal
from apx.axp import Actor, AuthContext
from apx.cli import main as cli_main
from apx.identity import ActorRegistry
from apx.protocol import MCPServer


def config(tmp_path: Path, extra: str = "") -> Path:
    path = tmp_path / "apx.toml"
    path.write_text('version=1\n[[hosts]]\nname="test"\ntransport="local"\n[[projects]]\nname="demo"\n' + extra)
    return path


class PrincipalTests(unittest.TestCase):
    def test_principal_is_axp_actor(self):
        self.assertIs(Principal, Actor)

    def test_principal_serialization_round_trip(self):
        principal = Principal(id="agent:worker:node-1", kind="agent", display_name="Worker Node 1")
        self.assertEqual(Actor.from_dict(principal.to_dict()), principal)

    def test_machine_kind_is_valid_alongside_host(self):
        Principal(id="machine:node-local", kind="machine")
        Principal(id="host:remote-node", kind="host")


class AuthContextTests(unittest.TestCase):
    def test_round_trip(self):
        context = AuthContext(principal_id="agent:worker:node-1", principal_type="agent", authentication_method="local_os", issuer="local")
        decoded = AuthContext.from_dict(context.to_dict())
        self.assertEqual(decoded, context)

    def test_to_dict_never_needs_a_raw_secret_field(self):
        context = AuthContext(principal_id="human:operator", principal_type="human", authentication_method="local_os", issuer="local")
        self.assertNotIn("token", context.to_dict())
        self.assertNotIn("password", context.to_dict())


class LocalAuthProviderTests(unittest.TestCase):
    def test_default_context_represents_how_identity_was_established(self):
        provider = LocalAuthProvider(ActorRegistry())
        context = provider.default_context("agent:worker:node-1")
        self.assertEqual(context.authentication_method, "local_os")
        self.assertEqual(context.principal_type, "agent")
        self.assertEqual(context.issuer, "local")

    def test_authenticate_falls_back_to_registry_default_actor(self):
        provider = LocalAuthProvider(ActorRegistry(default_actor="human:operator"))
        self.assertEqual(provider.authenticate({}).principal_id, "human:operator")


class AuthManagerTests(unittest.TestCase):
    def test_local_always_available(self):
        manager = AuthManager({}, ActorRegistry())
        self.assertIn("local", manager.providers)
        self.assertTrue(manager.allow_local_fallback)

    def test_unknown_method_raises(self):
        manager = AuthManager({}, ActorRegistry())
        with self.assertRaises(AuthenticationError):
            manager.authenticate("nonexistent", {})

    def test_default_context_used_when_no_explicit_auth_context_supplied(self):
        manager = AuthManager({}, ActorRegistry())
        self.assertEqual(manager.default_context("agent:worker:node-1").authentication_method, "local_os")


ROLE_CONFIG = '''
[[actors]]
id="agent:worker:node-1"
roles=["developer"]
[[roles]]
name="developer"
[[roles.allow]]
action="project.inspect"
[[roles.deny]]
action="host.shutdown"
'''


class AuthenticationVsAuthorizationTests(unittest.TestCase):
    """Authentication informs policy of who; it never grants authority -- PolicyEngine,
    keyed only on the local actor-id -> role mapping, still decides everything."""

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.cloud = APX(config(Path(self.temp.name), ROLE_CONFIG), plugins=False)

    def tearDown(self):
        self.temp.cleanup()

    def test_authenticated_locally_bound_by_policy_deny(self):
        denied = self.cloud.run("host.shutdown", actor="agent:worker:node-1", host="test")
        self.assertFalse(denied.ok)
        self.assertEqual(denied.error.code, "permission_denied")

    def test_authenticated_locally_bound_by_local_allow(self):
        allowed = self.cloud.run("project.inspect", actor="agent:worker:node-1", project="demo")
        self.assertTrue(allowed.ok)

    def test_authentication_status_action(self):
        cloud_open = APX(config(Path(self.temp.name)), plugins=False)
        result = cloud_open.run("auth.status")
        self.assertTrue(result.ok)
        self.assertIn("local", result.result.get("providers", []))


class MCPIdentityTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.cloud = APX(config(Path(self.temp.name)), plugins=False)

    def tearDown(self):
        self.temp.cleanup()

    def test_mcp_server_maps_to_a_specific_agent_profile_not_a_superuser(self):
        server = MCPServer(self.cloud, actor="agent:worker:node-1")
        self.assertEqual(server.actor, "agent:worker:node-1")

    def test_mcp_connection_emits_agent_connected(self):
        events = []
        self.cloud.events.subscribe("*", events.append, owner="test")
        MCPServer(self.cloud, actor="agent:worker:node-1")
        self.assertIn("agent.connected", [e.name for e in events])

    def test_auth_context_threads_through_mcp_tool_call(self):
        context = {"axp": "0.1", "type": "auth.context", "principal_id": "agent:worker:node-1", "principal_type": "agent", "authentication_method": "local_os", "issuer": "local"}
        server = MCPServer(self.cloud, actor="agent:worker:node-1", auth_context=context)
        request = {"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {"name": "project_inspect", "arguments": {"project": "demo"}}}
        response = server.dispatch(request)
        self.assertTrue(response["result"]["structuredContent"]["ok"])


class CLIParityTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.config_path = config(Path(self.temp.name))

    def tearDown(self):
        self.temp.cleanup()

    def test_auth_status_and_identity_list_via_cli(self):
        self.assertEqual(cli_main(["--config", str(self.config_path), "auth", "status"]), 0)
        self.assertEqual(cli_main(["--config", str(self.config_path), "identity", "list"]), 0)

    def test_identity_link_via_cli_persists_for_python_api(self):
        subdir = Path(self.temp.name) / "linked"
        subdir.mkdir()
        path = config(subdir, '[[actors]]\nid="agent:worker:node-1"\nroles=[]\n')
        code = cli_main(["--config", str(path), "identity", "link", "agent:worker:node-1", "--external-subject", "agent:ext-uuid-1"])
        self.assertEqual(code, 0)
        cloud = APX(path, plugins=False)
        self.assertEqual(cloud.actors.get("agent:worker:node-1").openpower_identity, "agent:ext-uuid-1")

    def test_identity_link_rejects_unknown_identity(self):
        code = cli_main(["--config", str(self.config_path), "identity", "link", "human:nobody", "--external-subject", "human:ext-uuid-1"])
        self.assertEqual(code, 1)

    def test_credential_lifecycle_via_cli(self):
        self.assertEqual(cli_main(["--config", str(self.config_path), "credential", "issue", "--principal", "agent:worker:node-1"]), 0)


if __name__ == "__main__":
    unittest.main()
