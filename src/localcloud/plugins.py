"""Plugin boundary for optional AXP contributions."""
from __future__ import annotations

import tomllib
from dataclasses import dataclass, field
from importlib.metadata import entry_points
from pathlib import Path
from typing import Any, Callable, Iterable, Protocol, TYPE_CHECKING

from .actions import ActionRegistry, RegisteredAction
from .axp import Capability, Context, Event, Resource
from .config import default_config_path
from .events import EventRouter

if TYPE_CHECKING:
    from .cloud import LocalCloud


@dataclass
class PluginAPI:
    actions: ActionRegistry
    events: EventRouter
    cloud: "LocalCloud"
    owner: str
    resources: list[Resource] = field(default_factory=list)
    capabilities: list[Capability] = field(default_factory=list)
    contexts: list[Context] = field(default_factory=list)
    resource_discoverers: list[Callable[[],Iterable[Resource]]] = field(default_factory=list)
    capability_discoverers: list[Callable[[str],Iterable[Capability]]] = field(default_factory=list)
    context_providers: list[Callable[[],Iterable[Context]]] = field(default_factory=list)

    def register_action(self, action: RegisteredAction) -> None: self.actions.register(action)
    def subscribe(self, pattern: str, listener) -> None: self.events.subscribe(pattern,listener,owner=self.owner)
    def emit(self, event: Event) -> Event: return self.events.emit(event)
    def add_resource(self, resource: Resource) -> None: self.resources.append(resource)
    def add_capability(self, capability: Capability) -> None: self.capabilities.append(capability)
    def add_context(self, context: Context) -> None: self.contexts.append(context)
    def discover_resources(self, discoverer: Callable[[],Iterable[Resource]]) -> None: self.resource_discoverers.append(discoverer)
    def discover_capabilities(self, discoverer: Callable[[str],Iterable[Capability]]) -> None: self.capability_discoverers.append(discoverer)
    def provide_context(self, provider: Callable[[],Iterable[Context]]) -> None: self.context_providers.append(provider)


class Plugin(Protocol):
    name: str
    def setup(self, api: PluginAPI) -> None: ...


class PluginManager:
    def __init__(self, actions: ActionRegistry, events: EventRouter, cloud: "LocalCloud"):
        self.actions,self.events,self.cloud=actions,events,cloud
        self.health: list[dict[str,Any]]=[]
        self.resources: list[Resource]=[]; self.capabilities: list[Capability]=[]; self.contexts: list[Context]=[]
        self.resource_discoverers=[]; self.capability_discoverers=[]; self.context_providers=[]

    def _setup(self, name: str, plugin: Any) -> None:
        api=PluginAPI(self.actions,self.events,self.cloud,name)
        try:
            if hasattr(plugin,"setup"): plugin.setup(api)
            elif hasattr(plugin,"register"): plugin.register(self.actions)
            else: raise TypeError("plugin must implement setup(api)")
            self.resources.extend(api.resources); self.capabilities.extend(api.capabilities); self.contexts.extend(api.contexts)
            self.resource_discoverers.extend((name,fn) for fn in api.resource_discoverers)
            self.capability_discoverers.extend((name,fn) for fn in api.capability_discoverers)
            self.context_providers.extend((name,fn) for fn in api.context_providers)
            self.health.append({"name":name,"ok":True})
        except Exception as error:
            self.health.append({"name":name,"ok":False,"error":str(error)})

    def load(self, config: str | Path | None) -> list[str]:
        path=Path(config).expanduser() if config else default_config_path()
        settings={}
        if path.exists(): settings=tomllib.loads(path.read_text(encoding="utf-8")).get("plugins",{})
        discord=settings.get("discord_webhook",{})
        if discord.get("enabled",False):
            try:
                from .integrations.discord_webhook import DiscordWebhookPlugin
                self._setup("discord_webhook",DiscordWebhookPlugin.from_config(discord))
            except Exception as error: self.health.append({"name":"discord_webhook","ok":False,"error":str(error)})
        for point in entry_points(group="localcloud.plugins"):
            try: self._setup(point.name,point.load()())
            except Exception as error: self.health.append({"name":point.name,"ok":False,"error":str(error)})
        return [item["name"] for item in self.health if item["ok"]]

    def _collect(self, providers, *args):
        values=[]
        for name,provider in providers:
            try: values.extend(provider(*args))
            except Exception as error: self.health.append({"name":name,"ok":False,"phase":"discovery","error":str(error)})
        return values

    def discover_resources(self): return self._collect(self.resource_discoverers)
    def discover_capabilities(self, host: str): return self._collect(self.capability_discoverers,host)
    def provide_contexts(self): return self._collect(self.context_providers)
