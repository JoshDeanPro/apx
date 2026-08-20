import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from apx import APX
from apx.credentials import (
    CredentialReference, CredentialRegistry, EnvironmentBackend, KeychainBackend,
    MockRotator, OpenBaoBackend, RotationWorkflow, SecretBackendError, SecretsManager,
    VaultwardenBackend,
)


def config(tmp_path: Path, extra: str = "") -> Path:
    path=tmp_path/"apx.toml"
    path.write_text('version=1\n[[hosts]]\nname="test"\ntransport="local"\n'+extra)
    return path


class EnvironmentBackendTests(unittest.TestCase):
    def test_health_and_reveal(self):
        backend=EnvironmentBackend(); ref=CredentialReference("token","generic","environment","APX_TEST_TOKEN")
        with patch.dict("os.environ",{},clear=False):
            self.assertFalse(backend.health(ref)["available"])
            with self.assertRaises(SecretBackendError): backend.reveal(ref)
        with patch.dict("os.environ",{"APX_TEST_TOKEN":"secret-value"}):
            self.assertTrue(backend.health(ref)["available"])
            self.assertEqual(backend.reveal(ref),"secret-value")

    def test_set_is_unsupported(self):
        backend=EnvironmentBackend(); ref=CredentialReference("token","generic","environment","X")
        with self.assertRaises(SecretBackendError): backend.set(ref,"value")


class KeychainBackendTests(unittest.TestCase):
    def test_get_set_reveal_use_security_cli_without_new_dependency(self):
        calls=[]
        def fake_run(argv,**kwargs):
            calls.append(argv)
            from types import SimpleNamespace
            if argv[1]=="add-generic-password": return SimpleNamespace(returncode=0,stdout="",stderr="")
            if argv[1]=="find-generic-password" and "-w" in argv: return SimpleNamespace(returncode=0,stdout="kv-value\n",stderr="")
            return SimpleNamespace(returncode=0,stdout="",stderr="")
        backend=KeychainBackend(run=fake_run)
        ref=CredentialReference("porkbun","dns","keychain","porkbun-token")
        with self.assertRaises(SecretBackendError): backend.set(ref,"abc123")
        self.assertTrue(backend.health(ref)["available"])
        self.assertEqual(backend.reveal(ref),"kv-value")
        self.assertTrue(all(argv[0]=="/usr/bin/security" for argv in calls))

    def test_darwin_only(self):
        with patch("apx.credentials.sys.platform","linux"):
            with self.assertRaises(SecretBackendError): KeychainBackend()

    def test_subprocess_timeout_becomes_a_secret_backend_error_not_a_raw_crash(self):
        import subprocess
        def timing_out(argv,**kwargs): raise subprocess.TimeoutExpired(cmd=argv,timeout=10)
        backend=KeychainBackend(run=timing_out)
        ref=CredentialReference("porkbun","dns","keychain","porkbun-token")
        with self.assertRaises(SecretBackendError): backend.health(ref)


class VaultwardenBackendTests(unittest.TestCase):
    def test_requires_unlocked_session(self):
        backend=VaultwardenBackend(run=lambda argv,**kw: None)
        ref=CredentialReference("porkbun","dns","vaultwarden","porkbun-token")
        with patch.dict("os.environ",{},clear=False):
            os.environ.pop("BW_SESSION",None)
            with self.assertRaises(SecretBackendError): backend.reveal(ref)

    def test_health_and_reveal_use_bw_cli_without_new_dependency(self):
        from types import SimpleNamespace
        calls=[]
        def fake_run(argv,**kwargs):
            calls.append(argv)
            if argv[:2]==["bw","get"] and argv[2]=="item":
                return SimpleNamespace(returncode=0,stdout='{"success":true,"data":{"id":"item-1","name":"porkbun-token","login":{"password":"kv-value"}}}',stderr="")
            if argv[:3]==["bw","get","password"]:
                return SimpleNamespace(returncode=0,stdout="kv-value\n",stderr="")
            return SimpleNamespace(returncode=1,stdout="",stderr="not found")
        backend=VaultwardenBackend(run=fake_run)
        ref=CredentialReference("porkbun","dns","vaultwarden","porkbun-token")
        with patch.dict("os.environ",{"BW_SESSION":"unlocked-session-token"}):
            self.assertTrue(backend.health(ref)["available"])
            self.assertEqual(backend.reveal(ref),"kv-value")
        self.assertTrue(all(argv[0]=="bw" for argv in calls))
        self.assertTrue(all("--session" not in argv for argv in calls))
        self.assertTrue(all("unlocked-session-token" not in argv for argv in calls))

    def test_set_edits_existing_item(self):
        from types import SimpleNamespace
        calls=[]
        def fake_run(argv,**kwargs):
            calls.append(argv)
            if argv[:2]==["bw","get"] and argv[2]=="item":
                return SimpleNamespace(returncode=0,stdout='{"success":true,"data":{"id":"item-1","name":"porkbun-token","login":{"password":"old"}}}',stderr="")
            if argv[:2]==["bw","encode"]:
                return SimpleNamespace(returncode=0,stdout="ZW5jb2RlZA==\n",stderr="")
            if argv[:2]==["bw","edit"]:
                return SimpleNamespace(returncode=0,stdout="",stderr="")
            return SimpleNamespace(returncode=1,stdout="",stderr="unexpected")
        backend=VaultwardenBackend(run=fake_run)
        ref=CredentialReference("porkbun","dns","vaultwarden","porkbun-token")
        with patch.dict("os.environ",{"BW_SESSION":"unlocked-session-token"}):
            result=backend.set(ref,"new-value")
        self.assertEqual(result["status"],"updated")

    def test_bw_not_installed_becomes_a_secret_backend_error(self):
        def missing(argv,**kwargs): raise FileNotFoundError("bw")
        backend=VaultwardenBackend(run=missing)
        ref=CredentialReference("porkbun","dns","vaultwarden","porkbun-token")
        with patch.dict("os.environ",{"BW_SESSION":"unlocked-session-token"}):
            with self.assertRaises(SecretBackendError): backend.reveal(ref)


class OpenBaoBackendTests(unittest.TestCase):
    def test_read_only_status_health_and_reveal_use_fake_transport(self):
        responses={
            ("GET","/v1/sys/health"):{"initialized":True,"sealed":False},
            ("GET","/v1/secret/metadata/cloudflare"):{"data":{"current_version":3,"versions":{"3":{}}}},
            ("GET","/v1/secret/data/cloudflare"):{"data":{"data":{"value":"real-token"}}},
        }
        def fake_request(method,path,body=None): return responses[(method,path)]
        with patch.dict("os.environ",{"OPENBAO_TOKEN":"root-token"}):
            backend=OpenBaoBackend("https://openbao.internal:8200","OPENBAO_TOKEN",request=fake_request)
            self.assertTrue(backend.status()["initialized"])
            ref=CredentialReference("cloudflare","dns","openbao","cloudflare")
            health=backend.health(ref)
            self.assertTrue(health["available"]); self.assertEqual(health["version"],3)
            self.assertEqual(backend.reveal(ref),"real-token")

    def test_requires_token_env_to_be_set(self):
        # exercise the real (unmocked) request path, which must check the token before any network I/O.
        backend=OpenBaoBackend("https://openbao.internal:8200","OPENBAO_TOKEN_MISSING")
        with patch.dict("os.environ",{},clear=False):
            os.environ.pop("OPENBAO_TOKEN_MISSING",None)
            with self.assertRaises(SecretBackendError): backend.status()


class SecretsManagerTests(unittest.TestCase):
    def test_get_never_returns_raw_value(self):
        registry=CredentialRegistry.from_config({"token":{"source":"environment","reference":"APX_TEST_TOKEN"}})
        manager=SecretsManager(registry)
        with patch.dict("os.environ",{"APX_TEST_TOKEN":"super-secret"}):
            result=manager.get("token")
        self.assertEqual(result["value"],"<redacted>")
        self.assertNotIn("super-secret",str(result))

    def test_reveal_returns_raw_value_when_called_directly(self):
        registry=CredentialRegistry.from_config({"token":{"source":"environment","reference":"APX_TEST_TOKEN"}})
        manager=SecretsManager(registry)
        with patch.dict("os.environ",{"APX_TEST_TOKEN":"super-secret"}):
            self.assertEqual(manager.reveal("token")["value"],"super-secret")

    def test_owner_is_surfaced_by_get_and_health_but_not_required(self):
        registry=CredentialRegistry.from_config({
            "owned":{"source":"environment","reference":"APX_TEST_TOKEN","owner":"human:operator"},
            "unowned":{"source":"environment","reference":"APX_TEST_TOKEN"},
        })
        manager=SecretsManager(registry)
        self.assertEqual(manager.get("owned")["owner"],"human:operator")
        self.assertEqual(manager.health("owned")["owner"],"human:operator")
        self.assertIsNone(manager.get("unowned")["owner"])


class RotationWorkflowTests(unittest.TestCase):
    def test_successful_rotation_activates_candidate_and_revokes_old(self):
        rotator=MockRotator()
        report=RotationWorkflow(rotator).run()
        self.assertTrue(report["ok"])
        self.assertEqual(rotator.current,"initial-candidate")
        self.assertEqual(rotator.revoked,["initial"])

    def test_failed_verification_keeps_old_credential(self):
        rotator=MockRotator(should_verify=False)
        report=RotationWorkflow(rotator).run()
        self.assertFalse(report["ok"]); self.assertEqual(report["stage"],"verify")
        self.assertEqual(rotator.current,"initial")
        self.assertEqual(rotator.revoked,[])

    def test_failed_post_activation_test_rolls_back(self):
        rotator=MockRotator(should_pass_test=False)
        report=RotationWorkflow(rotator).run()
        self.assertFalse(report["ok"]); self.assertEqual(report["stage"],"test")
        self.assertEqual(rotator.current,"initial")
        self.assertEqual(rotator.revoked,[])


class SecretActionsThroughAPXTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()

    def tearDown(self): self.temp.cleanup()

    def test_secret_set_result_never_echoes_value(self):
        cloud=APX(config(Path(self.temp.name),'[credentials.token]\nsource="environment"\nreference="APX_TEST_TOKEN"\n'),plugins=False)
        result=cloud.run("secret.set",id="token",value="brand-new-secret")
        self.assertNotIn("brand-new-secret",str(result.to_dict()))

    def test_secret_reveal_denied_for_agent_by_default_once_roles_configured(self):
        extra='''
[credentials.token]
source="environment"
reference="APX_TEST_TOKEN"
[[actors]]
id="agent:worker:node-1"
roles=["developer"]
[[actors]]
id="human:operator"
roles=["admin"]
[[roles]]
name="developer"
[[roles.allow]]
action="project.inspect"
[[roles]]
name="admin"
[[roles.allow]]
action="*"
'''
        cloud=APX(config(Path(self.temp.name),extra),plugins=False)
        with patch.dict("os.environ",{"APX_TEST_TOKEN":"super-secret"}):
            denied=cloud.run("secret.reveal",actor="agent:worker:node-1",id="token")
            self.assertFalse(denied.ok); self.assertEqual(denied.error.code,"permission_denied")
            allowed=cloud.run("secret.reveal",actor="human:operator",id="token")
            self.assertTrue(allowed.ok); self.assertEqual(allowed.result["value"],"super-secret")

    def test_secret_get_is_always_masked_regardless_of_actor(self):
        cloud=APX(config(Path(self.temp.name),'[credentials.token]\nsource="environment"\nreference="APX_TEST_TOKEN"\n'),plugins=False)
        with patch.dict("os.environ",{"APX_TEST_TOKEN":"super-secret"}):
            result=cloud.run("secret.get",id="token")
        self.assertNotIn("super-secret",str(result.to_dict()))

    def test_secret_rotate_never_reports_success_without_a_real_adapter(self):
        # No real provider rotator is wired into the live action this milestone -- it must
        # fail clearly rather than silently run MockRotator and report a fake success.
        cloud=APX(config(Path(self.temp.name),'[credentials.token]\nsource="environment"\nreference="APX_TEST_TOKEN"\n'),plugins=False)
        configured=cloud.run("secret.rotate",id="token")
        self.assertFalse(configured.ok)
        unconfigured=cloud.run("secret.rotate",id="not-a-real-credential")
        self.assertFalse(unconfigured.ok)
        self.assertIn("not-a-real-credential",unconfigured.error.message)


if __name__ == "__main__": unittest.main()
