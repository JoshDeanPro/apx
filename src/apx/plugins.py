# SPDX-License-Identifier: MIT
"""Plugin boundary for optional AXP contributions."""
from __future__ import annotations

import tomllib
from dataclasses import asdict, dataclass, field
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
    cloud: Any
    owner: str
    resources: list[Resource] = field(default_factory=list)
    capabilities: list[Capability] = field(default_factory=list)
    contexts: list[Context] = field(default_factory=list)
    resource_discoverers: list[Callable[[],Iterable[Resource]]] = field(default_factory=list)
    capability_discoverers: list[Callable[[str],Iterable[Capability]]] = field(default_factory=list)
    context_providers: list[Callable[[],Iterable[Context]]] = field(default_factory=list)
    allowed_credentials: tuple[str, ...] | None = None

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
        if self.allowed_credentials is not None and credential_id not in self.allowed_credentials:
            raise PermissionError("plugin credential access is outside its declared scope")
        # Provider actions resolve through the configured secret backend (environment,
        # Keychain, OpenBao), never directly through environment-only legacy lookup.
        return self.cloud.secrets.reveal(credential_id)["value"]


class _ScopedCredentials:
    """Read-only credential facade for a plugin's declared credential scope."""

    def __init__(self, registry, allowed: tuple[str, ...]):
        self._registry = registry
        self._allowed = frozenset(allowed)

    def _check(self, credential_id: str) -> None:
        if credential_id not in self._allowed:
            raise PermissionError("plugin credential access is outside its declared scope")

    def resolve(self, credential_id: str) -> str:
        self._check(credential_id)
        return self._registry.resolve(credential_id)

    def health(self) -> list[dict[str, Any]]:
        return [item for item in self._registry.health() if item.get("id") in self._allowed]

    def redact(self, value: Any) -> Any:
        return self._registry.redact(value)

    def redact_text(self, value: str) -> str:
        return self._registry.redact_text(value)


class _ScopedPluginCloud:
    """Minimal cloud facade for explicitly trusted external plugins.

    In-process plugins remain trusted code, but they no longer receive the global
    APX object by default. This facade exposes only the credential broker needed
    by provider-style plugins; core integrations continue to use the full object.
    """

    def __init__(self, cloud: "APX", allowed: tuple[str, ...]):
        self.credentials = _ScopedCredentials(cloud.credentials, allowed)
        self.secrets = _ScopedSecrets(cloud.secrets, allowed)


class _ScopedSecrets:
    """Credential backend facade that cannot enumerate or mutate other secrets."""

    def __init__(self, manager, allowed: tuple[str, ...]):
        self._manager = manager
        self._allowed = frozenset(allowed)

    def _check(self, credential_id: str) -> None:
        if credential_id not in self._allowed:
            raise PermissionError("plugin credential access is outside its declared scope")

    def get(self, credential_id: str) -> dict[str, Any]:
        self._check(credential_id)
        return self._manager.get(credential_id)

    def health(self, credential_id: str) -> dict[str, Any]:
        self._check(credential_id)
        return self._manager.health(credential_id)

    def reveal(self, credential_id: str, caller_scope: str | None = None) -> dict[str, Any]:
        self._check(credential_id)
        return self._manager.reveal(credential_id, caller_scope=caller_scope)

    def set(self, credential_id: str, value: str) -> dict[str, Any]:
        raise PermissionError("plugins cannot mutate credential stores")

    def rotate(self, credential_id: str, *args: Any, **kwargs: Any) -> dict[str, Any]:
        raise PermissionError("plugins cannot rotate credentials through the plugin facade")


class Plugin(Protocol):
    name: str
    def setup(self, api: PluginAPI) -> None: ...


@dataclass(frozen=True)
class PluginMetadata:
    name: str
    version: str
    description: str
    apx: str = "0.1"
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


@dataclass(frozen=True)
class PluginStatus:
    name: str
    available: bool
    installed: bool
    enabled: bool
    configured: bool
    credential_ready: bool
    healthy: bool
    active: bool
    state: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class PluginManager:
    def __init__(self, actions: ActionRegistry, events: EventRouter, cloud: "APX"):
        self.actions,self.events,self.cloud=actions,events,cloud
        self.health: list[dict[str,Any]]=[]
        self.resources: list[Resource]=[]; self.capabilities: list[Capability]=[]; self.contexts: list[Context]=[]
        self.resource_discoverers=[]; self.capability_discoverers=[]; self.context_providers=[]
        self.metadata: dict[str,PluginMetadata]={}
        self._settings: dict[str, Any] = {}
        self._document: dict[str, Any] = {}
        self._runtime_active: set[str] = set()

    def _setup(self, name: str, plugin: Any, *, trusted: bool = True) -> None:
        try:
            metadata=getattr(plugin,"metadata",None)
            if metadata is None: metadata=PluginMetadata(name,getattr(plugin,"version","unknown"),getattr(plugin,"description",name))
            if isinstance(metadata,dict): metadata=PluginMetadata(**metadata)
            if metadata.apx!="0.1": raise ValueError(f"plugin requires unsupported APX {metadata.apx}")
            plugin_cloud = self.cloud if trusted else _ScopedPluginCloud(self.cloud, metadata.credentials)
            api=PluginAPI(self.actions,self.events,plugin_cloud,name,allowed_credentials=metadata.credentials)
            self.metadata[name]=metadata
            if hasattr(plugin,"setup"): plugin.setup(api)
            elif hasattr(plugin,"register"): plugin.register(self.actions)
            else: raise TypeError("plugin must implement setup(api)")
            self.resources.extend(api.resources); self.capabilities.extend(api.capabilities); self.contexts.extend(api.contexts)
            self.resource_discoverers.extend((name,fn) for fn in api.resource_discoverers)
            self.capability_discoverers.extend((name,fn) for fn in api.capability_discoverers)
            self.context_providers.extend((name,fn) for fn in api.context_providers)
            self._runtime_active.add(name)
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
            self.health.append({"name":name,"ok":False,"error":self.cloud.credentials.redact_text(str(error))})

    def load(self, config: str | Path | None) -> list[str]:
        path=Path(config).expanduser() if config else default_config_path()
        document={}; settings={}
        if path.exists():
            document=tomllib.loads(path.read_text(encoding="utf-8")); settings=document.get("plugins",{})
        self._document = document
        self._settings = settings
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
        from .integrations.drift_plugin import Plugin as DriftPlugin
        self._setup("drift",DriftPlugin())
        self.health[-1].update(configured=True,status="ready")
        discord=settings.get("discord_webhook",{})
        if discord.get("enabled",False):
            try:
                from .integrations.discord_webhook import DiscordWebhookPlugin
                self._setup("discord_webhook",DiscordWebhookPlugin.from_config(discord))
            except Exception as error: self.health.append({"name":"discord_webhook","ok":False,"error":str(error)})
        for point in entry_points(group="apx.plugins"):
            # Discovering an installed third-party entry point must not import or
            # execute it. Activation requires an explicit enabled=true,
            # trusted=true grant in APX configuration. Metadata-only inspection is
            # intentionally sparse until that trust decision is made.
            settings_for_point = settings.get(point.name, {})
            if not isinstance(settings_for_point, dict):
                settings_for_point = {}
            if not (settings_for_point.get("enabled") and settings_for_point.get("trusted")):
                version = getattr(getattr(point, "dist", None), "version", "unknown")
                self.metadata.setdefault(point.name, PluginMetadata(point.name, str(version), "External plugin; explicit trust required"))
                self.health.append({"name": point.name, "ok": False, "status": "trust_required"})
                continue
            try: self._setup(point.name,point.load()(),trusted=False)
            except Exception as error: self.health.append({"name":point.name,"ok":False,"error":self.cloud.credentials.redact_text(str(error))})
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
    def _latest_health(self, name: str) -> dict[str, Any]:
        return next((item for item in reversed(self.health) if item.get("name") == name), {})

    def status(self, name: str) -> PluginStatus:
        available = name in self.metadata
        configuration = self._settings.get(name, {})
        if not isinstance(configuration, dict):
            configuration = {}
        enabled = bool(configuration.get("enabled", False))
        configured = bool(configuration)
        if name == "drift":
            enabled = True
            configured = True
        elif name == "databases":
            configured = bool(self._document.get("databases"))
            enabled = configured
        elif name in self._runtime_active and name not in self._settings:
            enabled = True
            configured = True
        health = self._latest_health(name)
        missing = tuple(str(item) for item in health.get("missing_credentials", ()))
        healthy = bool(health.get("ok", False)) and not health.get("error")
        credential_ready = not missing
        active = available and enabled and configured and name in self._runtime_active and healthy and credential_ready
        if not available:
            state = "not_available"
        elif active:
            state = "active"
        elif missing:
            state = "credentials_required"
        elif not enabled:
            state = "disabled"
        elif not configured:
            state = "configuration_required"
        elif health.get("status") == "trust_required":
            state = "trust_required"
        elif not healthy:
            state = "unhealthy"
        else:
            state = "ready"
        return PluginStatus(name, available, available, enabled, configured, credential_ready, healthy, active, state)

    def statuses(self) -> list[PluginStatus]:
        return [self.status(name) for name in sorted(self.metadata)]

    def inspect(self, name: str):
        if name not in self.metadata: raise KeyError(f"plugin {name!r} is not loaded")
        health=next((item for item in reversed(self.health) if item["name"]==name),{"name":name,"ok":True})
        return {"metadata":self.metadata[name].to_dict(),"health":health}
