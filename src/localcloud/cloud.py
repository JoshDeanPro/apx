from __future__ import annotations

from pathlib import Path
from typing import Any

from .actions import ActionError, CoreActions, RegisteredAction, build_registry
from .axp import ActionRequest, ActionResult, Connection, Event, Resource, ResourceRelationship, Capability, Context, StructuredError
from .config import load, load_document
from .credentials import CredentialRegistry
from .events import EventRouter
from .plugins import PluginManager


class LocalCloud:
    """Python API. CLI and MCP both delegate to this exact action path."""

    def __init__(self, config: str | Path | None = None, *, plugins: bool = True):
        self.config_path,self.config=load_document(config)
        self.hosts, self.projects = load(config)
        self.credentials=CredentialRegistry.from_config(self.config.get("credentials",{}))
        self.core = CoreActions(self.hosts, self.projects)
        self.actions = build_registry(self.core)
        self.connections=[]; self.adapters={}; self.connection_health=[]
        self._load_connections()
        self.events = EventRouter()
        self.plugin_manager = PluginManager(self.actions,self.events,self)
        self.plugins = self.plugin_manager.load(config) if plugins else []

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
        values=[Resource(id=f"host:{host.name}",kind="host",name=host.name,attributes=host.to_dict()) for host in self.hosts.values()]
        values.extend(Resource(id=f"project:{project.name}",kind="project",name=project.name,attributes={"description":project.description,"services":project.services,"domains":project.domains}) for project in self.projects.values())
        return values+self.plugin_manager.resources+self.plugin_manager.discover_resources()

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
        return [Capability(id=name,resource=f"host:{host}",available=value["available"],metadata={"command":value.get("command")}) for name,value in info["capabilities"].items()]+self.plugin_manager.capabilities+self.plugin_manager.discover_capabilities(host)

    def contexts(self) -> list[Context]:
        return [Context.from_mapping(f"project:{project.name}","project",project.context) for project in self.projects.values()]+self.plugin_manager.contexts+self.plugin_manager.provide_contexts()

    def action_definitions(self): return [action.definition() for action in self.actions.list()]
