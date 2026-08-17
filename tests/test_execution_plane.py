import asyncio
from pathlib import Path

from apx import APX
from apx.actions import RegisteredAction
from apx.execution import Procedure, ProcedureStep, ReasoningRequired


def config(path: Path, policy: str="") -> Path:
    target=path/"apx.toml"
    target.write_text('version=1\n[[hosts]]\nname="local"\ntransport="local"\n'+policy)
    return target


def schema(properties=None,required=()):
    return {"type":"object","properties":properties or {},"required":list(required),"additionalProperties":False}


def test_deterministic_execution_compact_result_and_metrics(tmp_path):
    cloud=APX(config(tmp_path),plugins=False)
    cloud.actions.register(RegisteredAction("test.ensure","Ensure state",lambda value:{"changed":value!="ready","state":"ready"},schema({"value":{"type":"string"}},("value",)),False,False,idempotent=True))
    result=cloud.run("test.ensure",value="ready")
    assert result.ok and result.execution["deterministic"] and result.execution["reasoning_calls"]==0
    assert result.compact()["result"]=={"changed":False,"state":"ready"}
    assert cloud.execution_metrics()["model_calls_avoided"]==1
    assert asyncio.run(cloud.run_async("test.ensure",value="old")).ok


def test_reasoning_boundary_does_not_invoke_a_model(tmp_path):
    cloud=APX(config(tmp_path),plugins=False)
    cloud.actions.register(RegisteredAction("test.ambiguous","Ambiguous",lambda:(_ for _ in ()).throw(ReasoningRequired("choose target",context={"candidates":2})),schema()))
    result=cloud.run("test.ambiguous")
    assert not result.ok and result.needs_reasoning
    assert result.error.code=="reasoning_required" and result.execution["model_calls_avoided"]==0
    assert cloud.execution_metrics()["reasoning_escalations"]==1


def test_procedure_reenters_policy_for_every_step(tmp_path):
    policy='''\ndefault_actor="agent:test"\n[[actors]]\nid="agent:test"\nkind="agent"\nroles=["limited"]\n[[roles]]\nname="limited"\n[[roles.allow]]\naction="procedure.demo"\n[[roles.deny]]\naction="test.mutate"\n'''
    cloud=APX(config(tmp_path,policy),plugins=False)
    called=[]
    cloud.actions.register(RegisteredAction("test.mutate","Mutate",lambda **values:called.append(values) or {"changed":True},schema(),False,False))
    cloud.register_procedure(Procedure("procedure.demo","Demo",(ProcedureStep("test.mutate"),),confirmation="none"))
    result=cloud.run("procedure.demo",actor="agent:test")
    assert not result.ok and not called
    assert result.error.code=="permission_denied" and result.error.details["step"]=="test.mutate"


def test_mcp_annotations_and_compact_tool_result(tmp_path):
    from apx.protocol import MCPServer
    cloud=APX(config(tmp_path),plugins=False)
    server=MCPServer(cloud)
    status=next(item for item in server.tools() if item["title"]=="service.status")
    restart=next(item for item in server.tools() if item["title"]=="service.restart")
    assert status["annotations"]["idempotentHint"] is True
    assert restart["annotations"]["idempotentHint"] is False
    response=server.dispatch({"jsonrpc":"2.0","id":1,"method":"tools/call","params":{"name":"host_list","arguments":{}}})
    structured=response["result"]["structuredContent"]
    assert structured["execution"]["deterministic"] and "data" not in structured


def test_compact_catalog_filters_namespaces(tmp_path):
    cloud=APX(config(tmp_path),plugins=False)
    catalog=cloud.actions.describe(namespaces=("service",))
    assert catalog and all(item["id"].startswith("service.") for item in catalog)
    assert all("args" in item and "deterministic" in item for item in catalog)
    assert len(str(catalog)) < len(str([item.definition().to_dict() for item in cloud.actions.list()]))


def test_configured_procedure_is_loaded_and_runs_without_reasoning(tmp_path):
    target=config(tmp_path)
    with target.open("a") as stream:
        stream.write('''\n[[procedures]]\nid="procedure.inspect-host"\ndescription="Inspect host predictably"\nconfirmation="none"\n[[procedures.steps]]\naction="host.status"\nforward=["host"]\n''')
    cloud=APX(target,plugins=False)
    result=cloud.run("procedure.inspect-host",host="local")
    assert result.ok and result.result["reasoning_calls"]==0 and len(result.result["steps"])==1


def test_service_transition_verifies_and_normalizes_state():
    from unittest.mock import patch
    from apx.actions import CoreActions
    from apx import Host
    from apx.transports import CommandResult
    class Transport:
        def __init__(self): self.values=["ActiveState=inactive\nSubState=dead\n","","ActiveState=active\nSubState=running\n"]
        def run(self,argv,**values): return CommandResult(tuple(argv),0,self.values.pop(0),"")
    transport=Transport(); core=CoreActions({"local":Host("local","local")},{})
    discovery={"capabilities":{"systemd":{"available":True}}}
    with patch("apx.actions.inspect_host",return_value=discovery),patch("apx.actions.transport_for",return_value=transport):
        result=core.service_control("start","local","demo")
    assert result["changed"] and result["verified"] and result["before"]=="inactive" and result["after"]=="active"


def test_launchd_service_control_starts_stops_and_verifies():
    from unittest.mock import patch
    from apx.actions import CoreActions
    from apx import Host
    from apx.transports import CommandResult
    class Transport:
        def __init__(self,values): self.values=list(values); self.argv=[]
        def run(self,argv,**kwargs):
            self.argv.append(argv)
            return CommandResult(tuple(argv),0,self.values.pop(0),"")
    def status(state): return f"gui/9999/demo = {{\n\tstate = {state}\n}}\n"
    core=CoreActions({"local":Host("local","local")},{})
    discovery={"capabilities":{"systemd":{"available":False},"launchd":{"available":True}}}
    getuid=patch("apx.actions.os.getuid",return_value=9999)

    transport=Transport([status("not running"),"",status("running")])
    with getuid,patch("apx.actions.inspect_host",return_value=discovery),patch("apx.actions.transport_for",return_value=transport):
        result=core.service_control("start","local","demo")
    assert result["changed"] and result["verified"] and result["before"]=="inactive" and result["after"]=="active"
    assert transport.argv[1]==["launchctl","kickstart","gui/9999/demo"]

    transport=Transport([status("running"),"",status("not running")])
    with getuid,patch("apx.actions.inspect_host",return_value=discovery),patch("apx.actions.transport_for",return_value=transport):
        result=core.service_control("stop","local","demo")
    assert result["changed"] and result["after"]=="inactive"
    assert transport.argv[1]==["launchctl","bootout","gui/9999/demo"]

    # already-running start is idempotent: no launchctl call at all beyond the status check
    transport=Transport([status("running")])
    with getuid,patch("apx.actions.inspect_host",return_value=discovery),patch("apx.actions.transport_for",return_value=transport):
        result=core.service_control("start","local","demo")
    assert not result["changed"] and len(transport.argv)==1

    # restart always forces a fresh instance, even if already running
    transport=Transport([status("running"),"",status("running")])
    with getuid,patch("apx.actions.inspect_host",return_value=discovery),patch("apx.actions.transport_for",return_value=transport):
        result=core.service_control("restart","local","demo")
    assert result["changed"]
    assert transport.argv[1]==["launchctl","kickstart","-k","gui/9999/demo"]
