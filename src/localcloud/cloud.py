from __future__ import annotations

from pathlib import Path
from typing import Any

from .actions import ActionError, CoreActions, build_registry
from .axp import ActionRequest, ActionResult, Event, Resource, Capability, Context, StructuredError
from .config import load
from .events import EventRouter
from .plugins import PluginManager


class LocalCloud:
    """Python API. CLI and MCP both delegate to this exact action path."""

    def __init__(self, config: str | Path | None = None, *, plugins: bool = True):
        self.hosts, self.projects = load(config)
        self.core = CoreActions(self.hosts, self.projects)
        self.actions = build_registry(self.core)
        self.events = EventRouter()
        self.plugin_manager = PluginManager(self.actions,self.events,self)
        self.plugins = self.plugin_manager.load(config) if plugins else []

    def run(self, action: str, **inputs: Any) -> ActionResult:
        target={key:inputs[key] for key in ("host","service","project","source_host","destination_host") if key in inputs and inputs[key] is not None}
        return self.execute(ActionRequest(action=action,target=target,input=inputs))

    def execute(self, request: ActionRequest) -> ActionResult:
        try:
            definition = self.actions.get(request.action)
            data = definition.handler(**request.input)
            result=ActionResult(action=definition.name,ok=True,result=data,request_id=request.request_id,target=request.target)
            self._emit_for_result(request,result)
            return result
        except (ActionError, RuntimeError, OSError, ValueError) as error:
            code="action.not_found" if "unknown action" in str(error) else "action.failed"
            result=ActionResult(action=request.action,ok=False,error=StructuredError(code,str(error)),request_id=request.request_id,target=request.target)
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

    def capabilities(self, host: str) -> list[Capability]:
        info=self.core.host_info(host)
        return [Capability(id=name,resource=f"host:{host}",available=value["available"],metadata={"command":value.get("command")}) for name,value in info["capabilities"].items()]+self.plugin_manager.capabilities+self.plugin_manager.discover_capabilities(host)

    def contexts(self) -> list[Context]:
        return [Context.from_mapping(f"project:{project.name}","project",project.context) for project in self.projects.values()]+self.plugin_manager.contexts+self.plugin_manager.provide_contexts()

    def action_definitions(self): return [action.definition() for action in self.actions.list()]
