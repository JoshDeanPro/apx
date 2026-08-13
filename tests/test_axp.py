import json
import platform
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from localcloud import ActionRequest, ActionResult, Context, Event, LocalCloud, Resource, StructuredError
from localcloud.actions import RegisteredAction
from localcloud.doctor import diagnose
from localcloud.events import EventRouter
from localcloud.integrations.discord_webhook import DiscordWebhookPlugin
from localcloud.plugins import PluginAPI
from localcloud.setup import initialize


def config(root: Path) -> Path:
    path=root/"localcloud.toml"
    path.write_text('version=1\n[[hosts]]\nname="test"\ntransport="local"\n')
    return path


class AXPTests(unittest.TestCase):
    def test_request_result_and_error_round_trip(self):
        request=ActionRequest("service.status",{"host":"vps"},{"host":"vps","service":"example"})
        self.assertEqual(ActionRequest.from_dict(json.loads(json.dumps(request.to_dict()))),request)
        result=ActionResult(request.action,False,error=StructuredError("service.missing","not found",{"service":"example"}),request_id=request.request_id,target=request.target)
        decoded=ActionResult.from_dict(json.loads(json.dumps(result.to_dict())))
        self.assertEqual(decoded.error.code,"service.missing")
        self.assertEqual(decoded.to_dict()["axp"],"0.1")

    def test_structured_execution_error(self):
        with tempfile.TemporaryDirectory() as directory:
            result=LocalCloud(config(Path(directory)),plugins=False).run("missing.action")
            self.assertFalse(result.ok); self.assertEqual(result.error.code,"action.not_found")

    def test_event_creation_and_routing(self):
        router=EventRouter(); received=[]
        router.subscribe("project.*",received.append,owner="test")
        event=router.emit(Event("project.deployed","test",{"project":"demo"}))
        self.assertEqual(received,[event])
        self.assertEqual(event.to_dict()["type"],"event")

    def test_plugin_actions_subscriptions_and_discord_listener(self):
        with tempfile.TemporaryDirectory() as directory:
            cloud=LocalCloud(config(Path(directory)),plugins=False)
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
            sent=[]; plugin=DiscordWebhookPlugin("https://example.invalid/webhook",("project.deployed",),lambda url,payload:sent.append((url,payload)))
            plugin.setup(PluginAPI(cloud.actions,cloud.events,cloud,"discord"))
            cloud.emit(Event("project.deployed","test",{"project":"demo"}))
            self.assertIn("project.deployed",sent[0][1]["content"])

    def test_context_is_structured(self):
        context=Context.from_mapping("project:demo","project",{"preferred_technologies":["Python"],"avoid":["Kafka"],"commands":{"test":"python -m unittest"}})
        self.assertEqual(context.avoid_technologies,("Kafka",))
        self.assertEqual(context.to_dict()["type"],"context")

    def test_core_axp_catalogs(self):
        with tempfile.TemporaryDirectory() as directory:
            cloud=LocalCloud(config(Path(directory)),plugins=False)
            self.assertEqual(cloud.resources()[0].kind,"host")
            self.assertTrue(any(item.id=="python" for item in cloud.capabilities("test")))
            self.assertEqual(cloud.action_definitions()[0].to_dict()["type"],"action.definition")

    def test_init_and_doctor(self):
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/"localcloud.toml"
            result=initialize(path,interactive=False)
            self.assertTrue(path.exists()); self.assertEqual(result["local"]["os"],platform.system())
            report=diagnose(path)
            self.assertTrue(report["config"]["ok"]); self.assertTrue(report["hosts"][0]["reachable"])
            self.assertTrue(report["mcp"]["available"])

    def test_doctor_reports_unhealthy_optional_plugin(self):
        with tempfile.TemporaryDirectory() as directory:
            path=config(Path(directory))
            with path.open("a") as stream: stream.write('\n[plugins.discord_webhook]\nenabled=true\nurl_env="LOCALCLOUD_TEST_MISSING_WEBHOOK"\n')
            with patch.dict("os.environ",{},clear=False):
                report=diagnose(path)
            self.assertFalse(report["ok"])
            self.assertEqual(report["plugins"][0]["name"],"discord_webhook")


if __name__ == "__main__": unittest.main()
