import io
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from apx import APX, Resource, VersionInfo
from apx.cli import main as cli_main
from apx.integrations.cloudflare import Plugin as CloudflarePlugin
from apx.integrations.godaddy import Plugin as GoDaddyPlugin
from apx.integrations.databases.aws import from_db_instance
from apx.integrations.databases.digitalocean import from_cluster
from apx.integrations.databases.models import parse_database_url, redact_database_url
from apx.integrations.databases.mysql import discover as discover_mysql
from apx.integrations.databases.postgres import discover as discover_postgres
from apx.integrations.databases.supabase import from_project
from apx.protocol import MCPServer
from apx.service_managers import manager_for
from apx.system import connection_status, scheduler_list, tailscale_status
from apx.transports import CommandResult, FallbackTransport
from apx.http import HTTPResult


def write_config(root: Path, extra: str = "") -> Path:
    path=root/"apx.toml"
    path.write_text('version=1\n[[hosts]]\nname="local"\ntransport="local"\ngroups=["production","compute"]\ntags=["critical"]\n'+extra)
    return path


class FakeTransport:
    def __init__(self,responses): self.responses=list(responses)
    def run(self,argv,**kwargs):
        value=self.responses.pop(0)
        return value if isinstance(value,CommandResult) else CommandResult(tuple(argv),0,value,"")


class FakeHTTPResponse:
    status=200
    headers={"Content-Type":"application/json"}
    def __init__(self,value): self.value=json.dumps(value).encode()
    def read(self,size): return self.value[:size]


def mocked_http(value): return patch("apx.http.HTTPClient.request",return_value=HTTPResult(200,{"Content-Type":"application/json"},json.dumps(value).encode()))


class IntegrationTests(unittest.TestCase):
    def test_version_and_provider_metadata(self):
        info=CloudflarePlugin({"credential":"cloudflare"}).metadata.version_info
        self.assertEqual(info.api_version,"v4"); self.assertEqual(info.compatibility,"supported")
        godaddy=GoDaddyPlugin({"credential":"godaddy"})
        versions={action.name:action.api_version for action in godaddy.actions}
        self.assertEqual(versions["godaddy.domain.list"],"v1")
        self.assertEqual(godaddy.version_info.supported,("v1","v2","v3"))
        with self.assertRaises(ValueError): VersionInfo(compatibility="bad")

    def test_groups_tags_and_multiple_membership(self):
        with tempfile.TemporaryDirectory() as directory:
            cloud=APX(write_config(Path(directory)),plugins=False)
            resource=next(item for item in cloud.resources() if item.id=="host:local")
            self.assertEqual(resource.groups,("production","compute")); self.assertIn("critical",resource.tags)
            self.assertTrue(cloud.run("group.add",resource="host:local",group="monitored").ok)
            self.assertIn("host:local",cloud.group_inspect("monitored")["resources"][0]["id"])
            self.assertTrue(cloud.run("group.remove",resource="host:local",group="monitored").ok)

    def test_credential_groups_health(self):
        with tempfile.TemporaryDirectory() as directory:
            path=write_config(Path(directory),'\n[credentials.cf]\nprovider="cloudflare"\nsource="environment"\nreference="LC_TEST_CF"\ngroups=["production","domains"]\ntags=["scoped"]\napi_version="v4"\n')
            with patch.dict(os.environ,{},clear=False):
                os.environ.pop("LC_TEST_CF",None); health=APX(path,plugins=False).credentials.health()[0]
            self.assertFalse(health["available"]); self.assertEqual(health["groups"],("production","domains")); self.assertEqual(health["api_version"],"v4")

    def test_database_parsing_redaction_and_provider_representations(self):
        value="postgresql://app:super-secret@db.example.com:5433/app?sslmode=require"
        database=parse_database_url(value,id="app")
        self.assertEqual((database.engine,database.host,database.port,database.database),("postgres","db.example.com",5433,"app"))
        self.assertNotIn("super-secret",redact_database_url(value)); self.assertIn("***",redact_database_url(value))
        supabase=from_project({"ref":"abcdefghijklmnopqrst","name":"demo"})
        self.assertEqual((supabase.engine,supabase.provider),("postgres","supabase"))
        aws=from_db_instance({"DBInstanceIdentifier":"orders","Engine":"aurora-mysql","EngineVersion":"8.0","Endpoint":{"Address":"orders.us-east-1.rds.amazonaws.com","Port":3306}})
        self.assertEqual((aws.provider,aws.engine,aws.version),("aws","aurora-mysql","8.0"))
        digitalocean=from_cluster({"id":"db1","engine":"advanced_pg","version":"17","connection":{"host":"db.db.ondigitalocean.com","port":25060,"ssl":True}})
        self.assertEqual((digitalocean.provider,digitalocean.engine),("digitalocean","postgres"))

    def test_postgres_and_mysql_tool_discovery(self):
        info={"capabilities":{"postgres":{"available":True,"command":"/usr/bin/psql"},"mysql":{"available":True,"command":"/usr/bin/mysql"}}}
        self.assertEqual(discover_postgres("server",info).id,"technology:postgres:server")
        self.assertEqual(discover_mysql("server",info).id,"technology:mysql:server")

    def test_database_action_discovers_native_services_without_clients(self):
        with tempfile.TemporaryDirectory() as directory:
            cloud=APX(write_config(Path(directory)))
            info={"capabilities":{"postgres":{"available":True,"version":"psql 16"},"mysql":{"available":False}}}
            services={"services":[{"name":"postgresql.service"},{"name":"mysql.service"}]}
            with patch.object(cloud.core,"host_info",return_value=info),patch.object(cloud.core,"service_list",return_value=services):
                result=cloud.run("database.discover",host="local")
            self.assertTrue(result.ok); self.assertEqual({item["engine"] for item in result.result["databases"]},{"postgres","mysql"})

    def test_connection_fallback(self):
        first=FakeTransport([CommandResult(("true",),255,"","offline")]); second=FakeTransport([CommandResult(("true",),0,"","")])
        result=FallbackTransport(__import__("apx").Host("host","ssh","one"),[first,second]).run(["true"])
        self.assertTrue(result.ok)

    def test_host_accepts_multiple_connection_methods(self):
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/"apx.toml"
            path.write_text('version=1\n[[hosts]]\nname="server"\n[[hosts.connections]]\nid="lan"\nadapter="ssh"\ntarget="server-lan"\npreferred=true\n[[hosts.connections]]\nid="tailnet"\nadapter="tailscale_ssh"\ntarget="server.tail.test"\n')
            cloud=APX(path,plugins=False)
            result=cloud.run("host.connection.list",host="server")
            self.assertTrue(result.ok); self.assertEqual([item["id"] for item in result.result["connections"]],["lan","tailnet"])

    def test_tailscale_discovery(self):
        info={"capabilities":{"tailscale":{"available":True}}}
        payload={"BackendState":"Running","Self":{"HostName":"mac","DNSName":"mac.tail.test.","TailscaleIPs":["198.51.100.1"]},"Peer":{"id":{"ID":"id","HostName":"home","DNSName":"home.tail.test.","TailscaleIPs":["198.51.100.2"],"Online":True}}}
        transport=FakeTransport(["1.80.0\n",json.dumps(payload)])
        with patch("apx.system.inspect_host",return_value=info),patch("apx.system.transport_for",return_value=transport):
            result=tailscale_status(__import__("apx").Host("mac","local"))
        self.assertTrue(result["connected"]); self.assertEqual(result["peers"][0]["hostname"],"home")

    def test_cron_systemd_timer_and_launchd_discovery(self):
        host=__import__("apx").Host("server","ssh","server")
        caps={"cron":{"available":True},"systemd":{"available":True},"launchd":{"available":False}}
        transport=FakeTransport(["0 2 * * * /usr/local/bin/backup\n","Thu 2026-08-13 03:00 UTC 1h left Wed 2026-08-12 03:00 UTC backup.timer backup.service\n"])
        with patch("apx.system.inspect_host",return_value={"capabilities":caps}),patch("apx.system.transport_for",return_value=transport): result=scheduler_list(host)
        self.assertEqual({job["scheduler"] for job in result["jobs"]},{"cron","systemd_timer"})
        caps={"cron":{"available":False},"systemd":{"available":False},"launchd":{"available":True}}
        transport=FakeTransport([json.dumps([{"name":"com.example.job","schedule":3600,"path":"/Library/x.plist","enabled":True}])])
        with patch("apx.system.inspect_host",return_value={"capabilities":caps}),patch("apx.system.transport_for",return_value=transport): result=scheduler_list(host)
        self.assertEqual(result["jobs"][0]["scheduler"],"launchd")

    def test_service_manager_capabilities_remain_native(self):
        systemd=manager_for({"capabilities":{"systemd":{"available":True},"launchd":{"available":False}}})
        launchd=manager_for({"capabilities":{"systemd":{"available":False},"launchd":{"available":True}}})
        self.assertIn("restart",systemd.mutations); self.assertIn("restart",launchd.mutations)

    def test_plugins_available_not_configured(self):
        with tempfile.TemporaryDirectory() as directory:
            cloud=APX(write_config(Path(directory)))
            inspected=cloud.plugin_manager.inspect("cloudflare")
            self.assertEqual(inspected["health"]["status"],"available_not_configured")
            porkbun=cloud.plugin_manager.inspect("porkbun")
            self.assertEqual(porkbun["health"]["status"],"available_not_configured")

    def test_provider_action_is_shared_by_python_cli_and_mcp(self):
        with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ,{"LC_CF_TOKEN":"fake-token"}):
            extra='\n[credentials.cf]\nsource="environment"\nreference="LC_CF_TOKEN"\n[plugins.cloudflare]\nenabled=true\ncredential="cf"\n'
            path=write_config(Path(directory),extra)
            with mocked_http({"success":True,"result":[]}):
                cloud=APX(path)
                self.assertTrue(cloud.run("cloudflare.zone.list").ok)
                server=MCPServer(cloud); self.assertIn("cloudflare_zone_list",{tool["name"] for tool in server.tools()})
                response=server.dispatch({"jsonrpc":"2.0","id":1,"method":"tools/call","params":{"name":"cloudflare_zone_list","arguments":{}}})
                self.assertTrue(response["result"]["structuredContent"]["ok"])
            with mocked_http({"success":True,"result":[]}),patch("builtins.print") as printed:
                self.assertEqual(cli_main(["--config",str(path),"run","cloudflare.zone.list"]),0)
                self.assertIn('"action": "cloudflare.zone.list"',printed.call_args.args[0])

    def test_cloudflare_and_discord_deeper_actions(self):
        with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ,{"LC_CF_TOKEN":"fake-token","LC_DC_TOKEN":"fake-token"}):
            extra=(
                '\n[credentials.cf]\nsource="environment"\nreference="LC_CF_TOKEN"\n[plugins.cloudflare]\nenabled=true\ncredential="cf"\n'
                '\n[credentials.dc]\nsource="environment"\nreference="LC_DC_TOKEN"\n[plugins.discord]\nenabled=true\nbot_credential="dc"\n'
            )
            path=write_config(Path(directory),extra)
            with mocked_http({"success":True,"result":[{"id":"setting-1"}]}):
                cloud=APX(path)
                result=cloud.run("cloudflare.setting.list",zone_id="zone-1")
                self.assertTrue(result.ok); self.assertEqual(result.result["data"],[{"id":"setting-1"}])
            with mocked_http([{"id":"role-1"}]):
                cloud=APX(path)
                result=cloud.run("discord.role.list",guild_id="guild-1")
                self.assertTrue(result.ok); self.assertEqual(result.result["data"],[{"id":"role-1"}])

    def test_paddle_plugin_loads_and_runs(self):
        with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ,{"LC_PADDLE_TOKEN":"fake-token"}):
            extra='\n[credentials.paddle]\nsource="environment"\nreference="LC_PADDLE_TOKEN"\n[plugins.paddle]\nenabled=true\ncredential="paddle"\n'
            path=write_config(Path(directory),extra)
            with mocked_http({"data":[{"id":"cus_01"}]}):
                cloud=APX(path)
                result=cloud.run("paddle.customer.list")
                self.assertTrue(result.ok); self.assertEqual(result.result["data"],[{"id":"cus_01"}])

    def test_purelymail_plugin_loads_and_runs_and_unwraps_body_errors(self):
        with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ,{"LC_PM_TOKEN":"fake-token"}):
            extra='\n[credentials.pm]\nsource="environment"\nreference="LC_PM_TOKEN"\n[plugins.purelymail]\nenabled=true\ncredential="pm"\n'
            path=write_config(Path(directory),extra)
            with mocked_http({"type":"success","result":{"domains":[]}}):
                cloud=APX(path)
                result=cloud.run("purelymail.domain.list")
                self.assertTrue(result.ok); self.assertEqual(result.result,{"domains":[]})
            with mocked_http({"type":"error","message":"invalid token"}):
                cloud=APX(path)
                result=cloud.run("purelymail.domain.list")
                self.assertFalse(result.ok); self.assertIn("invalid token",result.error.message)


if __name__=="__main__": unittest.main()
