import io
import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from localcloud import CredentialReference, Event, LocalCloud
from localcloud.adapters.http import HTTPAdapter
from localcloud.adapters.mcp import MCPStdioAdapter
from localcloud.adapters.webhook import WebhookAdapter
from localcloud.credentials import CredentialError, CredentialRegistry, REDACTED
from localcloud.scaffold import create
from localcloud.cli import main as cli_main


class FakeResponse:
    status=200
    headers={"Content-Type":"application/json","Set-Cookie":"private"}
    def __init__(self,body): self.body=json.dumps(body).encode()
    def read(self,size): return self.body[:size]


class ConnectionTests(unittest.TestCase):
    def test_credential_health_lazy_resolution_and_redaction(self):
        registry=CredentialRegistry({"api":CredentialReference("api","provider","environment","TEST_LOCALCLOUD_TOKEN")})
        with patch.dict(os.environ,{},clear=False):
            os.environ.pop("TEST_LOCALCLOUD_TOKEN",None)
            self.assertFalse(registry.health()[0]["available"])
            with self.assertRaises(CredentialError): registry.resolve("api")
        with patch.dict(os.environ,{"TEST_LOCALCLOUD_TOKEN":"rotated-value"}):
            self.assertEqual(registry.resolve("api"),"rotated-value")
            scrubbed=registry.redact({"nested":{"token":"anything","ordinary":"prefix rotated-value suffix"}})
            self.assertEqual(scrubbed["nested"],{"token":REDACTED,"ordinary":f"prefix {REDACTED} suffix"})

    def test_http_injects_secret_and_redacts_response(self):
        registry=CredentialRegistry({"api":CredentialReference("api",source="environment",reference="TEST_HTTP_SECRET")})
        captured={}
        def opener(request,timeout):
            captured["authorization"]=request.headers["Authorization"]
            return FakeResponse({"token":"returned-secret","ok":True})
        with patch.dict(os.environ,{"TEST_HTTP_SECRET":"input-secret"}):
            response=HTTPAdapter(registry,opener=opener).request("GET","https://example.test/resource",credential="api")
        self.assertEqual(captured["authorization"],"Bearer input-secret")
        self.assertEqual(response.body["token"],REDACTED)
        self.assertNotIn("Set-Cookie",response.headers)
        with self.assertRaises(ValueError): HTTPAdapter(registry,opener=opener).request("GET","http://example.test")

    def test_action_result_and_error_cannot_leak_known_secret(self):
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/"config.toml"; path.write_text('version=1\n[[hosts]]\nname="local"\ntransport="local"\n[credentials.api]\nsource="environment"\nreference="TEST_ACTION_SECRET"\n')
            with patch.dict(os.environ,{"TEST_ACTION_SECRET":"never-show-this"}):
                cloud=LocalCloud(path,plugins=False)
                from localcloud.actions import RegisteredAction
                cloud.actions.register(RegisteredAction("test.leak","test",lambda:{"ordinary":"never-show-this","password":"also-secret"},{"type":"object","properties":{}}))
                result=cloud.run("test.leak").to_dict()
            self.assertNotIn("never-show-this",json.dumps(result)); self.assertNotIn("also-secret",json.dumps(result))

    def test_webhook_sends_axp_event(self):
        seen={}
        class FakeHTTP:
            def request(self,*args,**kwargs): seen.update(args=args,kwargs=kwargs); return "ok"
        event=Event("project.deployed","test",{"project":"demo"})
        self.assertEqual(WebhookAdapter(FakeHTTP()).send("https://example.test/hook",event),"ok")
        self.assertEqual(seen["kwargs"]["body"]["type"],"event")

    def test_resource_relationships(self):
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/"config.toml"
            path.write_text('version=1\n[[hosts]]\nname="local"\ntransport="local"\n[[projects]]\nname="demo"\n[[projects.locations]]\nhost="local"\npath="/tmp/demo"\nrole="development"\n')
            relationship=LocalCloud(path,plugins=False).relationships()[0]
            self.assertEqual((relationship.source,relationship.relation,relationship.target),("project:demo","developed_on","host:local"))

    def test_scaffolds_are_small_and_valid(self):
        with tempfile.TemporaryDirectory() as directory:
            for kind,name in (("plugin","weather"),("action","weather.inspect"),("adapter","weather_api")):
                result=create(kind,name,directory)
                self.assertLessEqual(len(result["files"]),4)
                for file in Path(result["path"]).rglob("*.py"): compile(file.read_text(),str(file),"exec")

    def test_generic_cli_uses_shared_action(self):
        with tempfile.TemporaryDirectory() as directory:
            config=Path(directory)/"config.toml"; config.write_text('version=1\n[[hosts]]\nname="local"\ntransport="local"\n')
            with patch("builtins.print") as printed:
                code=cli_main(["--config",str(config),"run","host.inspect","--input",'{"host":"local"}'])
            self.assertEqual(code,0); self.assertIn('"type": "action.result"',printed.call_args.args[0])

    def test_stdio_mcp_adapter_discovers_localcloud(self):
        with tempfile.TemporaryDirectory() as directory:
            config=Path(directory)/"config.toml"; config.write_text('version=1\n[[hosts]]\nname="local"\ntransport="local"\n')
            command=[os.sys.executable,"-m","localcloud","--config",str(config),"mcp"]
            adapter=MCPStdioAdapter(command,timeout=10)
            try:
                tools=adapter.tools(); self.assertTrue(any(tool["name"]=="host_info" for tool in tools))
                response=adapter.call("host_info",{"host":"local"})
                self.assertFalse(response["isError"])
            finally: adapter.close()

    def test_configured_mcp_tools_become_axp_actions(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory); child=root/"child.toml"; child.write_text('version=1\n[[hosts]]\nname="child"\ntransport="local"\n')
            command=[os.sys.executable,"-m","localcloud","--config",str(child),"mcp"]
            parent=root/"parent.toml"
            parent.write_text('version=1\n[[hosts]]\nname="local"\ntransport="local"\n[[connections]]\nid="child"\nadapter="mcp_stdio"\ncommand='+json.dumps(command)+'\n')
            cloud=LocalCloud(parent,plugins=False)
            try:
                self.assertTrue(cloud.connection_health[0]["ok"])
                result=cloud.run("child.host_info",host="child")
                self.assertTrue(result.ok)
            finally:
                for adapter in cloud.adapters.values(): adapter.close()


if __name__=="__main__": unittest.main()
