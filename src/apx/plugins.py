"""Plugin boundary for optional AXP contributions."""
from __future__ import annotations

import tomllib
from dataclasses import dataclass, field
from importlib.metadata import entry_points
from pathlib import Path
from typing import Any, Callable, Iterable, Protocol, TYPE_CHECKING

from .actions import ActionRegistry, RegisteredAction
from .axp import Capability, Context, Event, Resource, VersionInfo
from .config import default_config_path
from .events import EventRouter

if TYPE_CHECKING:
    from .cloud import APX


@dataclass
class PluginAPI:
    actions: ActionRegistry
    events: EventRouter
    cloud: "APX"
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
    def credential(self, credential_id: str) -> str:
        # Provider actions resolve through the configured secret backend (environment,
        # Keychain, OpenBao), never directly through environment-only legacy lookup.
        return self.cloud.secrets.reveal(credential_id)["value"]


class Plugin(Protocol):
    name: str
    def setup(self, api: PluginAPI) -> None: ...


@dataclass(frozen=True)
class PluginMetadata:
    name: str
    version: str
    description: str
    axp: str = "0.1"
    resources: tuple[str,...] = ()
    actions: tuple[str,...] = ()
    events_emitted: tuple[str,...] = ()
    events_listened: tuple[str,...] = ()
    optional_dependencies: tuple[str,...] = ()
    credentials: tuple[str,...] = ()
    version_info: VersionInfo | None = None
    configuration: tuple[str,...] = ()

    def to_dict(self):
        from dataclasses import asdict
        return asdict(self)


class PluginManager:
    def __init__(self, actions: ActionRegistry, events: EventRouter, cloud: "APX"):
        self.actions,self.events,self.cloud=actions,events,cloud
        self.health: list[dict[str,Any]]=[]
        self.resources: list[Resource]=[]; self.capabilities: list[Capability]=[]; self.contexts: list[Context]=[]
        self.resource_discoverers=[]; self.capability_discoverers=[]; self.context_providers=[]
        self.metadata: dict[str,PluginMetadata]={}

    def _setup(self, name: str, plugin: Any) -> None:
        api=PluginAPI(self.actions,self.events,self.cloud,name)
        try:
            metadata=getattr(plugin,"metadata",None)
            if metadata is None: metadata=PluginMetadata(name,getattr(plugin,"version","unknown"),getattr(plugin,"description",name))
            if isinstance(metadata,dict): metadata=PluginMetadata(**metadata)
            if metadata.axp!="0.1": raise ValueError(f"plugin requires unsupported AXP {metadata.axp}")
            self.metadata[name]=metadata
            if hasattr(plugin,"setup"): plugin.setup(api)
            elif hasattr(plugin,"register"): plugin.register(self.actions)
            else: raise TypeError("plugin must implement setup(api)")
            self.resources.extend(api.resources); self.capabilities.extend(api.capabilities); self.contexts.extend(api.contexts)
            self.resource_discoverers.extend((name,fn) for fn in api.resource_discoverers)
            self.capability_discoverers.extend((name,fn) for fn in api.capability_discoverers)
            self.context_providers.extend((name,fn) for fn in api.context_providers)
            missing_credentials = [
                credential_id
                for credential_id in metadata.credentials
                if credential_id not in self.cloud.credentials.references
            ]
            health = {"name": name, "ok": not missing_credentials}
            if missing_credentials:
                health["missing_credentials"] = missing_credentials
            self.health.append(health)
        except Exception as error:
            self.health.append({"name":name,"ok":False,"error":str(error)})

    def load(self, config: str | Path | None) -> list[str]:
        path=Path(config).expanduser() if config else default_config_path()
        document={}; settings={}
        if path.exists():
            document=tomllib.loads(path.read_text(encoding="utf-8")); settings=document.get("plugins",{})
        builtins={
            "porkbun":"porkbun", "cloudflare":"cloudflare", "godaddy":"godaddy",
            "discord":"discord", "openai":"openai", "airtable":"airtable",
            "digitalocean":"digitalocean", "supabase":"supabase",
            "aws":"aws", "paddle":"paddle", "purelymail":"purelymail",
        }
        for name,module_name in builtins.items():
            try:
                module=__import__(f"apx.integrations.{module_name}",fromlist=["Plugin"])
                plugin=module.Plugin(settings.get(name,{}))
                if settings.get(name,{}).get("enabled",False): self._setup(name,plugin)
                else:
                    self.metadata[name]=plugin.metadata
                    self.health.append({"name":name,"ok":True,"configured":False,"status":"available_not_configured"})
            except Exception as error: self.health.append({"name":name,"ok":False,"error":str(error)})
        from .integrations.databases.plugin import Plugin as DatabasePlugin
        self._setup("databases",DatabasePlugin())
        self.health[-1].update(configured=bool(document.get("databases")),status="ready" if document.get("databases") else "discovery_only")
        discord=settings.get("discord_webhook",{})
        if discord.get("enabled",False):
            try:
                from .integrations.discord_webhook import DiscordWebhookPlugin
                self._setup("discord_webhook",DiscordWebhookPlugin.from_config(discord))
            except Exception as error: self.health.append({"name":"discord_webhook","ok":False,"error":str(error)})
        for point in entry_points(group="apx.plugins"):
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
    def inspect(self, name: str):
        if name not in self.metadata: raise KeyError(f"plugin {name!r} is not loaded")
        health=next((item for item in reversed(self.health) if item["name"]==name),{"name":name,"ok":True})
        return {"metadata":self.metadata[name].to_dict(),"health":health}
