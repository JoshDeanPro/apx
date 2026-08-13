from __future__ import annotations

from pathlib import Path
from typing import Any

from .actions import ActionError, CoreActions, RegisteredAction, build_registry
from .axp import ActionRequest, ActionResult, Connection, Event, Resource, ResourceRelationship, Capability, Context, StructuredError
from .config import load, load_document
from .credentials import CredentialRegistry
from .events import EventRouter
from .groups import GroupStore
from .plugins import PluginManager
from .system import connection_list, connection_status, scheduler_inspect, scheduler_list, tailscale_status


class LocalCloud:
    """Python API. CLI and MCP both delegate to this exact action path."""

    def __init__(self, config: str | Path | None = None, *, plugins: bool = True):
        self.config_path,self.config=load_document(config)
        self.hosts, self.projects = load(config)
        self.credentials=CredentialRegistry.from_config(self.config.get("credentials",{}))
        self.group_store=GroupStore(self.config_path,self.config.get("resources",{}))
        self.core = CoreActions(self.hosts, self.projects)
        self.actions = build_registry(self.core)
        self._register_operational_actions()
        self.connections=[]; self.adapters={}; self.connection_health=[]
        self._load_connections()
        self.events = EventRouter()
        self.plugin_manager = PluginManager(self.actions,self.events,self)
        self.plugins = self.plugin_manager.load(config) if plugins else []

    def _register_operational_actions(self) -> None:
        obj=lambda properties,required=():{"type":"object","properties":properties,"required":list(required),"additionalProperties":False}; string={"type":"string"}
        self.actions.register(RegisteredAction("host.connection.list","List configured host connection methods",lambda host:connection_list(self.core.host(host)),obj({"host":string},("host",))))
        self.actions.register(RegisteredAction("host.connection.status","Test host connection methods in fallback order",lambda host:connection_status(self.core.host(host)),obj({"host":string},("host",))))
        self.actions.register(RegisteredAction("tailscale.status","Inspect Tailscale on a host",lambda host:tailscale_status(self.core.host(host)),obj({"host":string},("host",))))
        self.actions.register(RegisteredAction("tailscale.peer.list","List safely visible Tailscale peers",lambda host:{"host":host,"peers":tailscale_status(self.core.host(host))["peers"]},obj({"host":string},("host",))))
        self.actions.register(RegisteredAction("scheduler.list","Discover cron, systemd timer, and launchd scheduled jobs",lambda host:scheduler_list(self.core.host(host)),obj({"host":string},("host",))))
        self.actions.register(RegisteredAction("scheduler.inspect","Inspect one scheduled job",lambda host,job:scheduler_inspect(self.core.host(host),job),obj({"host":string,"job":string},("host","job"))))
        self.actions.register(RegisteredAction("group.list","List resource groups",self.group_list,obj({})))
        self.actions.register(RegisteredAction("group.inspect","List resources in a group",self.group_inspect,obj({"group":string},("group",))))
        self.actions.register(RegisteredAction("group.add","Add a resource to a group",lambda resource,group:self.group_change(resource,group,True),obj({"resource":string,"group":string},("resource","group")),False,False))
        self.actions.register(RegisteredAction("group.remove","Remove a resource from a group",lambda resource,group:self.group_change(resource,group,False),obj({"resource":string,"group":string},("resource","group")),False,False))
        self.actions.register(RegisteredAction("resource.list","List/filter AXP resources",self.resource_list,obj({"kind":string,"group":string,"tag":string})))

    def _load_connections(self) -> None:
        for value in self.config.get("connections",[]):
            connection=Connection(value["id"],value["adapter"],value.get("resource"),value.get("credential"),{k:v for k,v in value.items() if k not in {"id","adapter","resource","credential"}})
            self.connections.append(connection)
            if connection.adapter=="mcp_stdio":
                from .adapters.mcp import MCPStdioAdapter
                try:
                    adapter=MCPStdioAdapter(list(connection.options.get("command",[])),timeout=int(connection.options.get("timeout",30)))
                    tools=adapter.tools(); self.adapters[connection.id]=adapter
                    for tool in tools:
                        action_id=f"{connection.id}.{tool['name']}"
                        def invoke(_tool=tool["name"],_adapter=adapter,**arguments):
                            response=_adapter.call(_tool,arguments)
                            if response.get("isError"): raise ActionError((response.get("content") or [{}])[0].get("text","MCP tool failed"))
                            return response.get("structuredContent") or response.get("content")
                        annotations=tool.get("annotations",{})
                        self.actions.register(RegisteredAction(action_id,f"MCP {connection.id}: {tool.get('description',tool['name'])}",invoke,tool.get("inputSchema",{"type":"object","properties":{}}),bool(annotations.get("readOnlyHint",False)),bool(annotations.get("destructiveHint",False))))
                    self.connection_health.append({"id":connection.id,"adapter":connection.adapter,"ok":True,"capabilities":len(tools)})
                except Exception as error: self.connection_health.append({"id":connection.id,"adapter":connection.adapter,"ok":False,"error":str(error)})
            else: self.connection_health.append({"id":connection.id,"adapter":connection.adapter,"ok":False,"error":"adapter is not configured by the core"})

    def run(self, action: str, **inputs: Any) -> ActionResult:
        target={key:inputs[key] for key in ("host","service","project","source_host","destination_host") if key in inputs and inputs[key] is not None}
        return self.execute(ActionRequest(action=action,target=target,input=inputs))

    def execute(self, request: ActionRequest) -> ActionResult:
        try:
            definition = self.actions.get(request.action)
            data = self.credentials.redact(definition.handler(**request.input))
            result=ActionResult(action=definition.name,ok=True,result=data,request_id=request.request_id,target=request.target)
            self._emit_for_result(request,result)
            return result
        except (ActionError, RuntimeError, OSError, ValueError) as error:
            code="action.not_found" if "unknown action" in str(error) else "action.failed"
            result=ActionResult(action=request.action,ok=False,error=StructuredError(code,self.credentials.redact_text(str(error))),request_id=request.request_id,target=request.target)
            self._emit_for_result(request,result)
            return result

    def _emit_for_result(self, request: ActionRequest, result: ActionResult) -> None:
        if not result.ok and request.action.startswith("service."): event_name="service.failed"
        elif not result.ok and request.action in {"host.inspect","host.info","host.status"}: event_name="host.offline"
        else: event_name={"service.start":"service.started","service.stop":"service.stopped","service.restart":"service.restarted","file.copy":"file.copied","file.sync":"file.synced","host.shutdown":"host.shutdown_requested"}.get(request.action,"action.completed" if result.ok else "action.failed")
        self.emit(Event(name=event_name,source="localcloud",subject=request.target,data={"action":request.action,"ok":result.ok,"error":result.error.to_dict() if result.error else None},correlation_id=request.request_id))

    def emit(self, event: Event) -> Event: return self.events.emit(event)

    def resources(self) -> list[Resource]:
        values=[Resource(id=f"host:{host.name}",kind="host",name=host.name,attributes={"transport":host.transport,"target":host.target,"connections":connection_list(host)["connections"]},groups=host.groups,tags=host.tags) for host in self.hosts.values()]
        values.extend(Resource(id=f"project:{project.name}",kind="project",name=project.name,attributes={"description":project.description,"services":project.services,"domains":project.domains},groups=project.groups,tags=project.tags) for project in self.projects.values())
        return [self.group_store.apply(value) for value in values+self.plugin_manager.resources+self.plugin_manager.discover_resources()]

    def group_list(self):
        groups={}
        for resource in self.resources():
            for group in resource.groups: groups.setdefault(group,[]).append(resource.id)
        return {"groups":[{"name":name,"resources":sorted(resources)} for name,resources in sorted(groups.items())]}

    def group_inspect(self,group: str):
        return {"group":group,"resources":[resource.to_dict() for resource in self.resources() if group in resource.groups or group in resource.tags]}

    def group_change(self,resource: str,group: str,add: bool):
        if resource not in {item.id for item in self.resources()}: raise ValueError(f"unknown resource {resource!r}")
        return self.group_store.change(resource,group,add)

    def resource_list(self,kind: str | None = None,group: str | None = None,tag: str | None = None):
        resources=self.resources()
        if kind: resources=[item for item in resources if item.kind==kind]
        if group: resources=[item for item in resources if group in item.groups]
        if tag: resources=[item for item in resources if tag in item.tags]
        return {"resources":[item.to_dict() for item in resources]}

    def relationships(self) -> list[ResourceRelationship]:
        relationships=[]
        role_relations={"development":"developed_on","production":"runs_on","archive":"backed_up_to","backup":"backed_up_to"}
        for project in self.projects.values():
            for location in project.locations:
                relationships.append(ResourceRelationship(f"project:{project.name}",role_relations.get(location.role,"located_on"),f"host:{location.host}",{"path":location.path,"role":location.role}))
        for value in self.config.get("relationships",[]): relationships.append(ResourceRelationship(value["source"],value["relation"],value["target"],value.get("metadata",{})))
        return relationships

    def capabilities(self, host: str) -> list[Capability]:
        info=self.core.host_info(host)
        return [Capability(id=name,resource=f"host:{host}",available=value["available"],metadata={"command":value.get("command"),"version":value.get("version")}) for name,value in info["capabilities"].items()]+self.plugin_manager.capabilities+self.plugin_manager.discover_capabilities(host)

    def contexts(self) -> list[Context]:
        return [Context.from_mapping(f"project:{project.name}","project",project.context) for project in self.projects.values()]+self.plugin_manager.contexts+self.plugin_manager.provide_contexts()

    def action_definitions(self): return [action.definition() for action in self.actions.list()]
