import base64
import hashlib
import hmac
import json
import os
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from apx import APX
from apx.auth import AuthenticationError, AuthManager, LocalAuthProvider, Principal
from apx.auth_openpower import OpenPowerAuthProvider, verify_jwt_hs256
from apx.axp import Actor, AuthContext
from apx.cli import main as cli_main
from apx.identity import ActorRegistry
from apx.protocol import MCPServer


def config(tmp_path: Path, extra: str = "") -> Path:
    path=tmp_path/"apx.toml"
    path.write_text('version=1\n[[hosts]]\nname="test"\ntransport="local"\n[[projects]]\nname="demo"\n'+extra)
    return path


def make_token(claims: dict, secret: str, alg: str = "HS256") -> str:
    def b64(data: bytes) -> str: return base64.urlsafe_b64encode(data).rstrip(b"=").decode()
    header=b64(json.dumps({"alg":alg,"typ":"JWT"}).encode())
    payload=b64(json.dumps(claims).encode())
    signing_input=f"{header}.{payload}".encode()
    signature=b"" if alg=="none" else hmac.new(secret.encode(),signing_input,hashlib.sha256).digest()
    return f"{header}.{payload}.{b64(signature)}"


class PrincipalTests(unittest.TestCase):
    def test_principal_is_axp_actor(self):
        self.assertIs(Principal, Actor)

    def test_principal_serialization_round_trip(self):
        principal=Principal(id="agent::mac",kind="agent",display_name=" on Mac")
        self.assertEqual(Actor.from_dict(principal.to_dict()),principal)

    def test_machine_kind_is_valid_alongside_host(self):
        Principal(id="machine:buddybox-home",kind="machine")
        Principal(id="host:vps",kind="host")


class AuthContextTests(unittest.TestCase):
    def test_round_trip(self):
        context=AuthContext(principal_id="agent::mac",principal_type="agent",authentication_method="local_os",issuer="local")
        decoded=AuthContext.from_dict(context.to_dict())
        self.assertEqual(decoded,context)

    def test_to_dict_never_needs_a_raw_secret_field(self):
        context=AuthContext(principal_id="human:ethan",principal_type="human",authentication_method="openpower",issuer="openpower")
        self.assertNotIn("token",context.to_dict()); self.assertNotIn("password",context.to_dict())


class LocalAuthProviderTests(unittest.TestCase):
    def test_default_context_represents_how_identity_was_established(self):
        provider=LocalAuthProvider(ActorRegistry())
        context=provider.default_context("agent::mac")
        self.assertEqual(context.authentication_method,"local_os")
        self.assertEqual(context.principal_type,"agent")
        self.assertEqual(context.issuer,"local")

    def test_authenticate_falls_back_to_registry_default_actor(self):
        provider=LocalAuthProvider(ActorRegistry(default_actor="human:ethan"))
        self.assertEqual(provider.authenticate({}).principal_id,"human:ethan")


class AuthManagerTests(unittest.TestCase):
    def test_local_always_available(self):
        manager=AuthManager({},ActorRegistry())
        self.assertIn("local",manager.providers)
        self.assertTrue(manager.allow_local_fallback)

    def test_unknown_method_raises(self):
        manager=AuthManager({},ActorRegistry())
        with self.assertRaises(AuthenticationError): manager.authenticate("nonexistent",{})

    def test_default_context_used_when_no_explicit_auth_context_supplied(self):
        manager=AuthManager({},ActorRegistry())
        self.assertEqual(manager.default_context("agent::mac").authentication_method,"local_os")


class JWTVerifierTests(unittest.TestCase):
    def setUp(self):
        self.secret="test-shared-secret"; self.now=int(time.time())

    def valid_claims(self,**overrides):
        claims={"sub":"agent::mac","principal_type":"agent","iss":"openpower.one","aud":"axp","exp":self.now+3600}
        claims.update(overrides); return claims

    def test_valid_token_verifies(self):
        token=make_token(self.valid_claims(),self.secret)
        claims=verify_jwt_hs256(token,self.secret,issuer="openpower.one",audience="axp")
        self.assertEqual(claims["sub"],"agent::mac")

    def test_expired_token_rejected(self):
        token=make_token(self.valid_claims(exp=self.now-3600),self.secret)
        with self.assertRaises(AuthenticationError): verify_jwt_hs256(token,self.secret,issuer="openpower.one",audience="axp")

    def test_wrong_issuer_rejected(self):
        token=make_token(self.valid_claims(iss="evil.example"),self.secret)
        with self.assertRaises(AuthenticationError): verify_jwt_hs256(token,self.secret,issuer="openpower.one",audience="axp")

    def test_wrong_audience_rejected(self):
        token=make_token(self.valid_claims(aud="something-else"),self.secret)
        with self.assertRaises(AuthenticationError): verify_jwt_hs256(token,self.secret,issuer="openpower.one",audience="axp")

    def test_alg_none_rejected(self):
        token=make_token(self.valid_claims(),self.secret,alg="none")
        with self.assertRaises(AuthenticationError): verify_jwt_hs256(token,self.secret,issuer="openpower.one",audience="axp")

    def test_tampered_signature_rejected(self):
        token=make_token(self.valid_claims(),self.secret)
        tampered=token[:-4]+"AAAA"
        with self.assertRaises(AuthenticationError): verify_jwt_hs256(tampered,self.secret,issuer="openpower.one",audience="axp")

    def test_wrong_secret_rejected(self):
        token=make_token(self.valid_claims(),"a-different-secret")
        with self.assertRaises(AuthenticationError): verify_jwt_hs256(token,self.secret,issuer="openpower.one",audience="axp")

    def test_malformed_token_rejected(self):
        with self.assertRaises(AuthenticationError): verify_jwt_hs256("not-a-jwt",self.secret)


class OpenPowerProviderTests(unittest.TestCase):
    def setUp(self):
        os.environ["APX_TEST_OP_SECRET"]="test-shared-secret"
        self.now=int(time.time())
        self.token=make_token({"sub":"agent::mac","principal_type":"agent","iss":"openpower.one","aud":"axp","exp":self.now+3600},"test-shared-secret")

    def test_live_authentication(self):
        provider=OpenPowerAuthProvider("https://openpower.one/api/v1","APX_TEST_OP_SECRET",request=lambda m,p:{"revoked":False})
        context=provider.authenticate({"token":self.token})
        self.assertEqual(context.authentication_method,"openpower"); self.assertEqual(context.principal_id,"agent::mac")

    def test_revoked_rejected(self):
        provider=OpenPowerAuthProvider("https://openpower.one/api/v1","APX_TEST_OP_SECRET",request=lambda m,p:{"revoked":True})
        with self.assertRaises(AuthenticationError): provider.authenticate({"token":self.token})

    def test_offline_without_cache_marked_distinctly(self):
        provider=OpenPowerAuthProvider("https://openpower.one/api/v1","APX_TEST_OP_SECRET",request=lambda m,p:(_ for _ in ()).throw(OSError("unreachable")))
        context=provider.authenticate({"token":self.token})
        self.assertEqual(context.authentication_method,"openpower_offline")

    def test_offline_with_cache_marked_distinctly_never_claims_fresh_validation(self):
        provider=OpenPowerAuthProvider("https://openpower.one/api/v1","APX_TEST_OP_SECRET",request=lambda m,p:{"revoked":False})
        provider.authenticate({"token":self.token})  # populate cache
        provider._request=lambda m,p:(_ for _ in ()).throw(OSError("unreachable"))
        context=provider.authenticate({"token":self.token})
        self.assertEqual(context.authentication_method,"cached_openpower")

    def test_offline_disabled_raises_instead_of_silently_degrading(self):
        provider=OpenPowerAuthProvider("https://openpower.one/api/v1","APX_TEST_OP_SECRET",request=lambda m,p:(_ for _ in ()).throw(OSError("unreachable")),allow_offline=False)
        with self.assertRaises(AuthenticationError): provider.authenticate({"token":self.token})

    def test_missing_shared_secret_env_raises(self):
        provider=OpenPowerAuthProvider("https://openpower.one/api/v1","APX_MISSING_SECRET_VAR")
        with self.assertRaises(AuthenticationError): provider.authenticate({"token":self.token})


OPENPOWER_CONFIG = '''
[auth.openpower]
enabled=true
endpoint="https://openpower.one/api/v1"
shared_secret_env="APX_TEST_OP_SECRET"
'''

ROLE_CONFIG = '''
[[actors]]
id="agent::mac"
roles=["developer"]
[[roles]]
name="developer"
[[roles.allow]]
action="project.inspect"
[[roles.deny]]
action="host.shutdown"
'''


class AuthenticationVsAuthorizationTests(unittest.TestCase):
    """Authentication informs policy of *who*; it never grants authority -- PolicyEngine,
    keyed only on the local actor-id -> role mapping, still decides everything."""

    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        os.environ["APX_TEST_OP_SECRET"]="test-shared-secret"
        self.cloud=APX(config(Path(self.temp.name),OPENPOWER_CONFIG+ROLE_CONFIG),plugins=False)
        self.cloud.auth.providers["openpower"]._request=lambda m,p:{"revoked":False}
        now=int(time.time())
        self.token=make_token({"sub":"agent::mac","principal_type":"agent","iss":"openpower.one","aud":"axp","exp":now+3600},"test-shared-secret")

    def tearDown(self): self.temp.cleanup()

    def test_authenticated_via_openpower_but_denied_locally(self):
        auth_result=self.cloud.run("auth.authenticate",method="openpower",credentials={"token":self.token})
        self.assertTrue(auth_result.ok); self.assertEqual(auth_result.result["authentication_method"],"openpower")
        # authentication succeeded, but local policy still denies host.shutdown for this actor
        denied=self.cloud.run("host.shutdown",actor="agent::mac",host="test")
        self.assertFalse(denied.ok); self.assertEqual(denied.error.code,"permission_denied")

    def test_authenticated_via_openpower_still_bound_by_local_allow(self):
        self.cloud.run("auth.authenticate",method="openpower",credentials={"token":self.token})
        allowed=self.cloud.run("project.inspect",actor="agent::mac",project="demo")
        self.assertTrue(allowed.ok)

    def test_authentication_failure_emits_event_without_leaking_the_bad_token(self):
        events=[]; self.cloud.events.subscribe("*",events.append,owner="test")
        bad_token=self.token[:-4]+"AAAA"
        result=self.cloud.run("auth.authenticate",method="openpower",credentials={"token":bad_token})
        self.assertFalse(result.ok)
        names=[e.name for e in events]
        self.assertIn("identity.authentication_failed",names)
        self.assertNotIn(bad_token,json.dumps([e.to_dict() for e in events]))

    def test_successful_authentication_emits_identity_authenticated_without_token_value(self):
        events=[]; self.cloud.events.subscribe("*",events.append,owner="test")
        self.cloud.run("auth.authenticate",method="openpower",credentials={"token":self.token})
        names=[e.name for e in events]
        self.assertIn("identity.authenticated",names)
        self.assertNotIn(self.token,json.dumps([e.to_dict() for e in events]))


class MCPIdentityTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.cloud=APX(config(Path(self.temp.name)),plugins=False)

    def tearDown(self): self.temp.cleanup()

    def test_mcp_server_maps_to_a_specific_agent_profile_not_a_superuser(self):
        server=MCPServer(self.cloud,actor="agent::mac")
        self.assertEqual(server.actor,"agent::mac")

    def test_mcp_connection_emits_agent_connected(self):
        events=[]; self.cloud.events.subscribe("*",events.append,owner="test")
        MCPServer(self.cloud,actor="agent::mac")
        self.assertIn("agent.connected",[e.name for e in events])

    def test_auth_context_threads_through_mcp_tool_call(self):
        context={"axp":"0.1","type":"auth.context","principal_id":"agent::mac","principal_type":"agent","authentication_method":"openpower","issuer":"openpower"}
        server=MCPServer(self.cloud,actor="agent::mac",auth_context=context)
        request={"jsonrpc":"2.0","id":1,"method":"tools/call","params":{"name":"project_inspect","arguments":{"project":"demo"}}}
        response=server.dispatch(request)
        self.assertTrue(response["result"]["structuredContent"]["ok"])


class CLIParityTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.config_path=config(Path(self.temp.name))

    def tearDown(self): self.temp.cleanup()

    def test_auth_status_and_identity_list_via_cli(self):
        self.assertEqual(cli_main(["--config",str(self.config_path),"auth","status"]),0)
        self.assertEqual(cli_main(["--config",str(self.config_path),"identity","list"]),0)

    def test_identity_link_via_cli_persists_for_python_api(self):
        subdir=Path(self.temp.name)/"linked"; subdir.mkdir()
        path=config(subdir,'[[actors]]\nid="agent::mac"\nroles=[]\n')
        code=cli_main(["--config",str(path),"identity","link","agent::mac","--openpower-subject","agent:op-uuid-1"])
        self.assertEqual(code,0)
        cloud=APX(path,plugins=False)
        self.assertEqual(cloud.actors.get("agent::mac").openpower_identity,"agent:op-uuid-1")

    def test_identity_link_rejects_unknown_identity(self):
        code=cli_main(["--config",str(self.config_path),"identity","link","human:nobody","--openpower-subject","human:op-uuid-1"])
        self.assertEqual(code,1)

    def test_credential_lifecycle_via_cli(self):
        self.assertEqual(cli_main(["--config",str(self.config_path),"credential","issue","--principal","agent::mac"]),0)


if __name__ == "__main__": unittest.main()
