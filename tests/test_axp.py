import json
import platform
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from apx import ActionRequest, ActionResult, Context, Event, APX, Resource, StructuredError
from apx.actions import RegisteredAction
from apx.events import EventRouter
from apx.integrations.discord_webhook import DiscordWebhookPlugin
from apx.plugins import PluginAPI, PluginManager, PluginMetadata
from apx.setup import initialize


def config(root: Path) -> Path:
    path=root/"apx.toml"
    path.write_text('version=1\n[[hosts]]\nname="test"\ntransport="local"\n')
    return path


class AXPTests(unittest.TestCase):
    def test_request_result_and_error_round_trip(self):
        request=ActionRequest("service.status",{"host":"vps"},{"host":"vps","service":"example"})
        self.assertEqual(ActionRequest.from_dict(json.loads(json.dumps(request.to_dict()))),request)
        result=ActionResult(request.action,False,error=StructuredError("service.missing","not found",{"service":"example"}),request_id=request.request_id,target=request.target)
        decoded=ActionResult.from_dict(json.loads(json.dumps(result.to_dict())))
        self.assertEqual(decoded.error.code,"service.missing")
        self.assertEqual(decoded.to_dict()["apx"],"0.1")
        self.assertNotIn("axp",decoded.to_dict())

    def test_structured_execution_error(self):
        with tempfile.TemporaryDirectory() as directory:
            result=APX(config(Path(directory)),plugins=False).run("missing.action")
            self.assertFalse(result.ok); self.assertEqual(result.error.code,"action.not_found")

    def test_event_creation_and_routing(self):
        router=EventRouter(); received=[]
        router.subscribe("project.*",received.append,owner="test")
        event=router.emit(Event("project.deployed","test",{"project":"demo"}))
        self.assertEqual(received,[event])
        self.assertEqual(event.to_dict()["type"],"event")

    def test_plugin_actions_subscriptions_and_discord_listener(self):
        with tempfile.TemporaryDirectory() as directory:
            cloud=APX(config(Path(directory)),plugins=False)
            seen=[]
            class Demo:
                name="demo"
                def setup(self,api):
                    api.register_action(RegisteredAction("demo.echo","Echo",lambda value:{"value":value},{"type":"object","properties":{"value":{"type":"string"}}}))
                    api.subscribe("demo.*",seen.append)
                    api.discover_resources(lambda:[Resource("demo:one","demo","one")])
            api=PluginAPI(cloud.actions,cloud.events,cloud,"demo")
            Demo().setup(api)
            self.assertTrue(cloud.run("demo.echo",value="ok").ok)
            self.assertEqual(api.resource_discoverers[0]()[0].kind,"demo")
            cloud.emit(Event("demo.finished","demo")); self.assertEqual(len(seen),1)
            sent=[]; plugin=DiscordWebhookPlugin("discord_webhook",("project.deployed",),lambda url,payload:sent.append((url,payload)))
            cloud.credentials.references["discord_webhook"]=__import__("apx").CredentialReference("discord_webhook","discord","environment","TEST_DISCORD_WEBHOOK")
            plugin.setup(PluginAPI(cloud.actions,cloud.events,cloud,"discord"))
            with patch.dict("os.environ",{"TEST_DISCORD_WEBHOOK":"https://example.invalid/webhook"}): cloud.emit(Event("project.deployed","test",{"project":"demo"}))
            self.assertIn("project.deployed",sent[0][1]["content"])

    def test_context_is_structured(self):
        context=Context.from_mapping("project:demo","project",{"preferred_technologies":["Python"],"avoid":["Kafka"],"commands":{"test":"python -m unittest"}})
        self.assertEqual(context.avoid_technologies,("Kafka",))
        self.assertEqual(context.to_dict()["type"],"context")

    def test_core_axp_catalogs(self):
        with tempfile.TemporaryDirectory() as directory:
            cloud=APX(config(Path(directory)),plugins=False)
            self.assertEqual(cloud.resources()[0].kind,"host")
            self.assertTrue(any(item.id=="python" for item in cloud.capabilities("test")))
            self.assertEqual(cloud.action_definitions()[0].to_dict()["type"],"action.definition")

    def test_init_creates_valid_configuration(self):
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/"apx.toml"
            result=initialize(path,interactive=False)
            self.assertTrue(path.exists())
            self.assertEqual(result["local"]["os"],platform.system())
            cloud=APX(path,plugins=False)
            self.assertGreater(len(cloud.resources()),0)

    def test_plugin_metadata_reports_missing_credential_reference(self):
        with tempfile.TemporaryDirectory() as directory:
            cloud=APX(config(Path(directory)),plugins=False)
            class NeedsCredential:
                metadata=PluginMetadata("needs_credential","1.0.0","test",credentials=("provider_token",))
                def setup(self,api): pass
            manager=PluginManager(cloud.actions,cloud.events,cloud)
            manager._setup("needs_credential",NeedsCredential())
            self.assertFalse(manager.health[0]["ok"])
            self.assertEqual(manager.health[0]["missing_credentials"],["provider_token"])


if __name__ == "__main__": unittest.main()
