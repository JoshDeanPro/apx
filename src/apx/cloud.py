# SPDX-License-Identifier: MPL-2.0
from __future__ import annotations

import secrets
import asyncio
import sys
import time
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from jsonschema import ValidationError
from jsonschema.validators import Draft202012Validator

from .actions import ActionError, CoreActions, RegisteredAction, build_registry
from .auth import AuthenticationError, AuthManager
from .axp import APX_PROTOCOL_VERSION, ActionReceipt, ActionRequest, ActionResult, ActorDescriptor, Connection, Event, PolicyDecision, PreparedAction, Resource, ResourceRelationship, Capability, Context, StructuredError, parse_resource_ref
from .config import load, load_document
from .credentials import ActorCredentialError, ActorCredentialStore, CredentialRegistry, KeychainBackend, OpenBaoBackend, SecretBackendError, SecretsManager, VaultwardenBackend
from .enrollment import EnrollmentError, EnrollmentStore
from .events import EventRouter
from .groups import GroupStore
from .identity import ActorRegistry, DEFAULT_ACTOR, IdentityLinkStore
from .missions import MissionError, MissionStore
from .plugins import PluginManager
from .providers import ActionProvider, ProviderManifest, RemoteProvider, validate_provider
from .policy import PolicyEngine, ScopedRule, scope_values
from .state import SECURITY_STATES, StateStore
from .system import connection_list, connection_status, scheduler_inspect, scheduler_list, tailscale_status
from .fabric import CapabilityGraph
from .execution import ExecutionPlane, Procedure, ProcedureFailed, ProcedureRegistry, ProcedureStep, ReasoningRequired
from .blueprints import Blueprint, BlueprintError, BlueprintRegistry, BlueprintStep, BlueprintStore
from .blueprints import apply as _run_blueprint_apply, plan as _run_blueprint_plan
from . import filesystem as _filesystem
from .grants import Grant, GrantError, GrantStore
from . import agents as _agents
from .agents import AgentError, AgentStore
from .nodes import NodeError, NodeStore
from . import search as _search
from . import environment_ingest as _environment_ingest
from .transports import transport_for


class APX:
    """Python API. CLI and MCP both delegate to this exact action path."""

    def __init__(self, config: str | Path | None = None, *, plugins: bool = True):
        self.config_path,self.config=load_document(config)
        self.hosts, self.projects = load(config)
        self.credentials=CredentialRegistry.from_config(self.config.get("credentials",{}))
        self.secrets=SecretsManager(self.credentials,self._secret_backends())
        self.group_store=GroupStore(self.config_path,self.config.get("resources",{}))
        self.actors=ActorRegistry.from_config(self.config.get("actors",[]),self.config.get("default_actor",DEFAULT_ACTOR))
        self.identity_links=IdentityLinkStore(self.config_path); self.identity_links.apply(self.actors)
        self.policy=PolicyEngine.from_config(self.config.get("roles",[]),self.actors)
        self.state=StateStore(self.config_path,self.config.get("state",{}).get("default","normal"))
        self.missions=MissionStore(self.config_path)
        self.enrollment=EnrollmentStore(self.config_path)
        self.actor_credentials=ActorCredentialStore(self.config_path)
        self.auth=self._build_auth_manager()
        self._pairing_codes: dict[str, dict[str, Any]] = {}
        self.core = CoreActions(self.hosts, self.projects)
        self.actions = build_registry(self.core)
        self.execution=ExecutionPlane(); self.procedures=ProcedureRegistry()
        self._register_operational_actions()
        self._register_mission_actions()
        self._register_identity_actions()
        self._register_filesystem_actions()
        self.blueprints=BlueprintStore(self.config_path)
        self.blueprint_registry=BlueprintRegistry()
        self._register_blueprint_actions()
        self.grants=GrantStore(self.config_path)
        self._register_grant_actions()
        self._register_discovery_actions()
        self._register_adapter_actions()
        self.nodes=NodeStore(self.config_path)
        self._register_node_actions()
        self._register_search_actions()
        self._register_update_actions()
        self._register_fleet_actions()
        self.agents=AgentStore(self.config_path)
        self._register_agent_actions()
        self.connections=[]; self.adapters={}; self.connection_health=[]
        self._load_connections()
        self._register_environment_ingest_actions()
        self.bridges={}; self.bridge_health: list[dict[str, Any]] = []
        self._load_bridges()
        self.events = EventRouter()
        self.providers: dict[str, ActionProvider | RemoteProvider] = {}
        self._used_authorizations: set[str] = set()
        self._load_providers()
        self.plugin_manager = PluginManager(self.actions,self.events,self)
        self.plugins = self.plugin_manager.load(config) if plugins else []
        self._load_procedures()
        # Loaded last, deliberately: a config-defined Blueprint can reference any action
        # registered anywhere above (grant.*/node.*/search.*/agent.*, or a plugin-provided
        # action), and this is the only point in __init__ where the full registry is
        # actually complete -- loading earlier raised spurious "unknown action" errors for
        # perfectly valid references to actions that simply hadn't been registered yet.
        self._load_blueprint_library()
        self._load_blueprints_from_config()

    def _load_procedures(self) -> None:
        for value in self.config.get("procedures",[]):
            steps=tuple(ProcedureStep(item["action"],dict(item.get("input",{})),tuple(item.get("forward",()))) for item in value.get("steps",()))
            self.register_procedure(Procedure(value["id"],value.get("description",value["id"]),steps,value.get("risk","low_change"),value.get("confirmation","confirm")))

    def _register_filesystem_actions(self) -> None:
        obj=lambda properties,required=():{"type":"object","properties":properties,"required":list(required),"additionalProperties":False}
        s={"type":"string"}; boolean={"type":"boolean"}; a=self.actions.register; R=RegisteredAction
        a(R("directory.ensure","Ensure a local directory exists",_filesystem.directory_ensure,obj({"path":s,"dry_run":boolean},("path",)),False,False,supports_dry_run=True,idempotent=True,risk="low_change",resource_type="filesystem"))
        a(R("file.template.ensure","Ensure a local file exists with given content (mode=safe never overwrites a differing file)",_filesystem.file_template_ensure,obj({"path":s,"content":s,"mode":s,"dry_run":boolean},("path","content")),False,False,supports_dry_run=True,idempotent=True,risk="low_change",resource_type="filesystem"))
        a(R("file.exists","Check whether a local path exists",_filesystem.file_exists,obj({"path":s},("path",)),True,False))

    _CONFIRMATION_RANK={"none":0,"delegated":1,"confirm":2,"step_up":3,"transaction":4,"security_critical":5}

    def _register_blueprint(self, blueprint: Blueprint) -> None:
        available={item.name for item in self.actions.list()}
        missing=[step.action for step in blueprint.steps if step.action not in available]
        if missing: raise BlueprintError(f"blueprint {blueprint.name!r} references unknown action(s): {', '.join(sorted(set(missing)))}")
        strongest=max((self._CONFIRMATION_RANK[self.actions.get(step.action).confirmation] for step in blueprint.steps),default=0)
        if strongest>self._CONFIRMATION_RANK["confirm"]:
            raise BlueprintError(f"blueprint {blueprint.name!r} contains a step requiring stronger confirmation than blueprint.apply provides ({blueprint.name!r} step confirmation exceeds 'confirm'); register it as its own action or Procedure instead")
        self.blueprint_registry.register(blueprint,available)

    def _load_blueprint_library(self) -> None:
        from .blueprint_library import BUILT_IN_BLUEPRINTS
        for blueprint in BUILT_IN_BLUEPRINTS: self._register_blueprint(blueprint)

    def _load_blueprints_from_config(self) -> None:
        from uuid import uuid4
        for value in self.config.get("blueprints",[]):
            steps=tuple(BlueprintStep(item["id"],item["action"],dict(item.get("args",{})),tuple(item.get("after",())),item.get("when")) for item in value["steps"])
            blueprint=Blueprint(
                stable_id=value.get("stable_id") or f"bp_{uuid4().hex[:12]}",
                name=value["name"],version=value.get("version","1.0.0"),description=value.get("description",value["name"]),
                steps=steps,aliases=tuple(value.get("aliases",())),category=value.get("category","project"),
                tags=tuple(value.get("tags",())),inputs=value.get("inputs",{}),requires=tuple(value.get("requires",())),
                includes=tuple(value.get("includes",())),resulting_capabilities=tuple(value.get("resulting_capabilities",())),
                provenance="project",migrates_from=tuple(value.get("migrates_from",())),
            )
            self._register_blueprint(blueprint)

    def _register_blueprint_actions(self) -> None:
        obj=lambda properties,required=():{"type":"object","properties":properties,"required":list(required),"additionalProperties":False}
        s={"type":"string"}; a=self.actions.register; R=RegisteredAction
        a(R("blueprint.list","List latest-version Blueprints known to APX",self.blueprint_list,obj({"category":s,"tag":s})))
        a(R("blueprint.search","Search Blueprints by name/description/category/tag",self.blueprint_search,obj({"query":s,"category":s,"tag":s})))
        a(R("blueprint.show","Inspect a Blueprint's full (composed, DAG-resolved) definition",self.blueprint_show,obj({"blueprint":s,"version":s},("blueprint",))))
        a(R("blueprint.status","Show a project's applied-Blueprint history and recorded capabilities",self.blueprint_status,obj({"project":s},("project",))))
        a(R("blueprint.plan","Dry-run a Blueprint against a project/inputs; changes nothing",self.blueprint_plan,obj({"blueprint":s,"version":s,"project":s,"inputs":{"type":"object"}},("blueprint",)),True,False,tags=("blueprint",)))
        a(R("blueprint.apply","Apply a Blueprint -- runs its action graph, changing only what's not already satisfied",self.blueprint_apply,obj({"blueprint":s,"version":s,"project":s,"inputs":{"type":"object"}},("blueprint",)),False,False,confirmation="confirm",idempotent=True,tags=("blueprint",)))
        a(R("blueprint.upgrade","Re-apply a Blueprint at its latest version, converging an already-applied project forward",self.blueprint_upgrade,obj({"blueprint":s,"project":s,"inputs":{"type":"object"}},("blueprint","project")),False,False,confirmation="confirm",idempotent=True,tags=("blueprint",)))

    def _register_grant_actions(self) -> None:
        obj=lambda properties,required=():{"type":"object","properties":properties,"required":list(required),"additionalProperties":False}
        s={"type":"string"}; arr={"type":"array","items":s}; a=self.actions.register; R=RegisteredAction
        non_empty_arr={"type":"array","items":s,"minItems":1}
        a(R("grant.issue","Delegate a bounded, independently-expiring authority (a Grant) to an actor",self.grant_issue,
            obj({"subject":s,"actions":non_empty_arr,"resources":arr,"constraints":{"type":"object"},"reason":s,"expires_at":s},("subject","actions")),
            False,False,tags=("grant",),resource_type="grant"))
        a(R("grant.list","List Grants, optionally filtered by subject",self.grant_list,obj({"subject":s,"include_expired":{"type":"boolean"}})))
        a(R("grant.inspect","Inspect a Grant",self.grant_inspect,obj({"grant":s},("grant",))))
        a(R("grant.revoke","Revoke a Grant immediately",self.grant_revoke,obj({"grant":s},("grant",)),False,False,tags=("grant",),resource_type="grant"))

    def _register_discovery_actions(self) -> None:
        obj=lambda properties,required=():{"type":"object","properties":properties,"required":list(required),"additionalProperties":False}
        s={"type":"string"}
        self.actions.register(RegisteredAction(
            "discovery.capabilities",
            "Identity-aware, policy-filtered list of actions a subject can currently see -- the DISCOVER protocol operation",
            lambda subject=None,namespaces=None,compact=True:self.discover(subject,namespaces=tuple(namespaces or ()),compact=compact),
            obj({"subject":s,"namespaces":{"type":"array","items":s},"compact":{"type":"boolean"}}),
        ))

    def _register_adapter_actions(self) -> None:
        obj=lambda properties,required=():{"type":"object","properties":properties,"required":list(required),"additionalProperties":False}
        s={"type":"string"}
        self.actions.register(RegisteredAction(
            "adapter.test","Run APX Adapter conformance checks against a remote provider URL, a locally-registered provider, or a Bridge",
            self.adapter_test,obj({"url":s,"provider":s,"bridge":s,"timeout":{"type":"integer"}}),
        ))

    def adapter_test(self, url: str | None = None, provider: str | None = None, bridge: str | None = None, timeout: int = 10) -> dict[str, Any]:
        from .adapter_test import AdapterTestError, run as _run_adapter_test
        try: return _run_adapter_test(self,url=url,provider=provider,bridge=bridge,timeout=timeout)
        except AdapterTestError as error: raise ActionError(str(error)) from error

    def _register_node_actions(self) -> None:
        obj=lambda properties,required=():{"type":"object","properties":properties,"required":list(required),"additionalProperties":False}
        s={"type":"string"}
        self.actions.register(RegisteredAction("node.list","List cached hardware/capability profiles for known Nodes",self.node_list,obj({})))
        self.actions.register(RegisteredAction("node.inspect","Read a Node's cached hardware/capability profile, refreshing if stale",self.node_inspect,obj({"host":s,"force":{"type":"boolean"}},("host",))))
        self.actions.register(RegisteredAction("node.refresh","Force a fresh hardware/capability discovery for a Node",self.node_refresh,obj({"host":s},("host",)),False,False,idempotent=True,risk="low_change"))
        self.actions.register(RegisteredAction("node.permissions","Real, policy-evaluated list of what an actor may currently do on a specific Node -- not a cosmetic settings echo",self.node_permissions,obj({"host":s,"subject":s},("host",))))

    def _register_search_actions(self) -> None:
        obj=lambda properties,required=():{"type":"object","properties":properties,"required":list(required),"additionalProperties":False}
        s={"type":"string"}
        self.actions.register(RegisteredAction("search.query","Deterministic local search over known Nodes, Projects, Actions, Blueprints, Connections, and Grants -- no AI, no embeddings",self.search_query,obj({"query":s,"kinds":{"type":"array","items":s},"limit":{"type":"integer"}},("query",))))

    def _register_update_actions(self) -> None:
        obj=lambda properties,required=():{"type":"object","properties":properties,"required":list(required),"additionalProperties":False}
        self.actions.register(RegisteredAction("system.version","Report the running apx package version and git commit",self.system_version,obj({})))
        self.actions.register(RegisteredAction("system.check_update","Check, read-only, whether the APX software is behind: a development checkout is compared against its upstream branch, an installed runtime reports its configured update source",self.system_check_update,obj({})))
        self.actions.register(RegisteredAction("system.update","Update the APX software, never the machine's local state: a development checkout fast-forwards (refusing to run with uncommitted changes), an installed runtime installs its configured source",self.system_update,obj({"reinstall":{"type":"boolean"}}),False,False,confirmation="none",idempotent=True,risk="low_change"))

    def system_version(self) -> dict[str,Any]:
        from .selfupdate import version_info
        return version_info()

    def system_check_update(self) -> dict[str,Any]:
        from .selfupdate import check_for_updates
        return check_for_updates(config=self.config)

    def system_update(self, reinstall: bool = True) -> dict[str,Any]:
        from .selfupdate import UpdateError, apply_update
        try: return apply_update(reinstall=reinstall,config=self.config)
        except UpdateError as error: raise ActionError(str(error)) from error

    def _register_fleet_actions(self) -> None:
        obj=lambda properties,required=():{"type":"object","properties":properties,"required":list(required),"additionalProperties":False}
        self.actions.register(RegisteredAction("fleet.health","Parallel health probe over every configured Host and every registered *.status Action -- replaces polling each one individually",self.fleet_health,obj({})))

    def fleet_health(self, actor: str | None = None) -> dict[str,Any]:
        """One composite read-only probe, run concurrently since most of the work is
        network-bound (SSH to each Host, HTTP to each provider) -- sequential would be
        as slow as the sum of every timeout instead of the slowest single one."""
        import concurrent.futures
        actor_id=actor or self.actors.resolve_default()

        def probe_host(name: str) -> tuple[str,dict[str,Any]]:
            try: return name,self.core.host_status(name)
            except Exception as error: return name,{"error":str(error)}

        def probe_provider(action_name: str) -> tuple[str,dict[str,Any]]:
            try:
                outcome=self.run(action_name,actor=actor_id)
                return action_name,(outcome.result if outcome.ok else {"error":outcome.error.message if outcome.error else "failed"})
            except Exception as error: return action_name,{"error":str(error)}

        # Only zero-argument *.status actions qualify -- host.status/service.status
        # etc. need a target and are already covered by the per-host probe above.
        status_actions=sorted(a.name for a in self.actions.list() if a.name.endswith(".status") and not a.schema.get("required"))
        hosts={};providers={}
        with concurrent.futures.ThreadPoolExecutor(max_workers=max(1,len(self.hosts)+len(status_actions))) as pool:
            future_kind={pool.submit(probe_host,name):hosts for name in self.hosts}
            future_kind.update({pool.submit(probe_provider,name):providers for name in status_actions})
            for future in concurrent.futures.as_completed(future_kind):
                name,result=future.result()
                future_kind[future][name]=result
        problems=[f"host {name}: {result['error']}" for name,result in hosts.items() if isinstance(result,dict) and "error" in result]
        problems+=[f"{name}: {result['error']}" for name,result in providers.items() if isinstance(result,dict) and "error" in result]
        return {"subject":actor_id,"hosts":hosts,"providers":providers,"healthy":not problems,"problems":problems}

    def _register_agent_actions(self) -> None:
        obj=lambda properties,required=():{"type":"object","properties":properties,"required":list(required),"additionalProperties":False}
        s={"type":"string"}
        self.actions.register(RegisteredAction(
            "agent.plan","Render (but do not write) the run.sh/systemd-unit/prompt a Standing Agent setup would produce -- the DRY-RUN for agent.setup",
            self.agent_plan,obj({"name":s,"host":s,"repo":s,"description":s,"project_description":s,"user":s,"runtime":s,"model":s,"effort":s,
                "timeout":{"type":"integer"},"idle_gap":{"type":"integer"},"status_command":s,"test_command":s},("name","host","repo")),
        ))
        self.actions.register(RegisteredAction(
            "agent.setup","Stand up a new Standing Agent (the palis-autopilot pattern: a coding-agent CLI run to completion, one iteration at a time, forever, under systemd) on a configured Node. Writes config; never starts the loop unless start=true.",
            self.agent_setup,obj({"name":s,"host":s,"repo":s,"description":s,"project_description":s,"user":s,"runtime":s,"model":s,"effort":s,
                "timeout":{"type":"integer"},"idle_gap":{"type":"integer"},"status_command":s,"test_command":s,
                "force":{"type":"boolean"},"enable":{"type":"boolean"},"start":{"type":"boolean"}},("name","host","repo")),
            False,False,confirmation="confirm",tags=("agent",),resource_type="agent",
        ))
        self.actions.register(RegisteredAction("agent.list","List Standing Agents apx has set up",self.agent_list,obj({"host":s})))
        self.actions.register(RegisteredAction("agent.inspect","Inspect a Standing Agent's configuration and current service state",self.agent_inspect,obj({"name":s},("name",))))
        self.actions.register(RegisteredAction("agent.logs","Read a Standing Agent's systemd journal",self.agent_logs,obj({"name":s,"lines":{"type":"integer"}},("name",))))
        self.actions.register(RegisteredAction(
            "agent.remove","Stop tracking a Standing Agent. purge=true additionally stops+disables the service and deletes its files from the Node.",
            self.agent_remove,obj({"name":s,"purge":{"type":"boolean"}},("name",)),False,False,confirmation="confirm",tags=("agent",),resource_type="agent",
        ))

    def agent_plan(self, name: str, host: str, repo: str, **options: Any) -> dict[str,Any]:
        if host not in self.hosts: raise ActionError(f"unknown host {host!r}")
        try:
            init_system=_agents.detect_init_system(self.hosts[host])
            return _agents.render(name,repo=repo,init_system=init_system,**{k:v for k,v in options.items() if v is not None})
        except AgentError as error: raise ActionError(str(error)) from error

    def agent_setup(self, actor: str, name: str, host: str, repo: str, force: bool = False, enable: bool = False,
                     start: bool = False, **options: Any) -> dict[str,Any]:
        if host not in self.hosts: raise ActionError(f"unknown host {host!r}")
        host_item=self.hosts[host]
        try:
            init_system=_agents.detect_init_system(host_item)
            rendered=_agents.render(name,repo=repo,init_system=init_system,**{k:v for k,v in options.items() if v is not None})
            deployed=_agents.deploy(host_item,rendered,force=force)
        except AgentError as error: raise ActionError(str(error)) from error
        transport=transport_for(host_item)
        if enable and init_system=="systemd":
            result=transport.run(["systemctl","enable",deployed["unit_name"]],timeout=15)
            if not result.ok: raise ActionError(f"systemctl enable failed on {host}: {result.stderr.strip()}")
        entry=self.agents.record(name,host=host,unit_name=deployed["unit_name"],repo=repo,runtime=rendered["runtime"],
            model=options.get("model") or "opus",effort=options.get("effort") or "medium",state_dir=rendered["state_dir"],
            run_script_path=rendered["run_script_path"],prompt_path=rendered["prompt_path"],unit_path=rendered["unit_path"],created_by=actor)
        start_result=None
        if start:
            outcome=self.run("service.start",actor=actor,host=host,service=deployed["unit_name"])
            start_result=outcome.compact()
            if not outcome.ok: raise ActionError(f"agent {name!r} was configured but failed to start: {outcome.error.message if outcome.error else 'unknown error'}")
        return {**deployed,"enabled":enable,"started":bool(start),"start_result":start_result,"agent":entry}

    def agent_list(self, host: str | None = None) -> dict[str,Any]: return {"agents":self.agents.list(host=host)}

    def agent_inspect(self, name: str) -> dict[str,Any]:
        try: entry=self.agents.get(name)
        except AgentError as error: raise ActionError(str(error)) from error
        try: status=self.core.service_status(entry["host"],entry["unit_name"])
        except ActionError as error: status={"error":str(error)}
        return {**entry,"service_status":status}

    def agent_logs(self, name: str, lines: int = 100) -> dict[str,Any]:
        try: entry=self.agents.get(name)
        except AgentError as error: raise ActionError(str(error)) from error
        return self.core.logs_read(entry["host"],entry["unit_name"],lines)

    def agent_remove(self, actor: str, name: str, purge: bool = False) -> dict[str,Any]:
        try: entry=self.agents.get(name)
        except AgentError as error: raise ActionError(str(error)) from error
        purged=None
        if purge:
            host_item=self.hosts.get(entry["host"])
            if host_item is None: raise ActionError(f"host {entry['host']!r} is no longer configured; cannot purge remote files")
            transport=transport_for(host_item)
            transport.run(["systemctl","disable","--now",entry["unit_name"]],timeout=30)
            remove=transport.run(["rm","-f",entry["run_script_path"],entry["unit_path"]],timeout=15)
            purged={"stopped_and_disabled":True,"files_removed":remove.ok}
            transport.run(["systemctl","daemon-reload"],timeout=15)
        try: removed=self.agents.remove(name)
        except AgentError as error: raise ActionError(str(error)) from error
        return {"removed":removed,"purged":purged}

    def node_list(self) -> dict[str, Any]: return {"nodes": self.nodes.list()}

    def node_inspect(self, host: str, force: bool = False) -> dict[str, Any]:
        try: return self.nodes.refresh(self.core.host(host), force=force)
        except (ActionError, NodeError) as error: raise ActionError(str(error)) from error

    def node_refresh(self, host: str) -> dict[str, Any]: return self.node_inspect(host, force=True)

    def node_permissions(self, host: str, subject: str | None = None) -> dict[str, Any]:
        """Iterates the real action registry and calls the same PolicyEngine.evaluate()
        execute() uses, scoped to this Node -- an actor's effective Node permissions are
        computed from the live policy, never a separately-tracked settings mirror that
        could drift from what's actually enforced."""
        if host not in self.hosts: raise ActionError(f"unknown host {host!r}")
        actor_id=subject or self.actors.resolve_default()
        extra_allow=self._extra_allow(actor_id); state=self.state.get()
        allowed=[]
        for action in self.actions.list():
            if action.name in self.INTROSPECTION_ACTIONS: continue
            decision=self.policy.evaluate(actor_id,action.name,{"host":host},state,extra_allow)
            if decision.allowed: allowed.append(action.name)
        return {"host":host,"subject":actor_id,"allowed":sorted(allowed),"count":len(allowed)}

    def search_query(self, query: str, kinds: list[str] | None = None, limit: int = 20) -> dict[str, Any]:
        return {"query":query,"results":_search.query(self,query,kinds=tuple(kinds or ()),limit=limit)}

    def _load_bridges(self) -> None:
        """Optional Bridges (browser.*, machine.*, home-assistant.*), config-gated so
        APX Core never depends on them. Mirrors _load_connections/_load_providers: a
        misconfigured or missing optional dependency is recorded in bridge_health, it
        never crashes APX startup."""
        for value in self.config.get("bridges",[]):
            kind=value.get("type")
            try:
                if kind=="psutil":
                    from .bridges.psutil import PsutilBridge
                    bridge=PsutilBridge()
                elif kind=="browser":
                    from .bridges.browser import BrowserBridge, LazyPlaywrightDriver
                    bridge=BrowserBridge(LazyPlaywrightDriver(headless=value.get("headless",True)))
                else: raise ValueError(f"unknown bridge type {kind!r}")
                self.register_bridge(bridge)  # bridge.id (a fixed class attribute) is the real registry/adapter.test key, not any config-supplied name
                self.bridge_health.append({"id":bridge.id,"type":kind,"ok":True})
            except Exception as error:
                self.bridge_health.append({"id":value.get("id",kind),"type":kind,"ok":False,"error":str(error)})

    def _load_providers(self) -> None:
        for value in self.config.get("providers",[]):
            if not value.get("enabled",True): continue
            if value.get("type")=="reference":
                from .examples.subscriptions import build_reference_provider
                self.register_provider(build_reference_provider())
            elif value.get("origin"):
                self.connect_provider(value["origin"])

    def _secret_backends(self) -> dict[str, Any]:
        backends={}
        secrets_config=self.config.get("secrets",{})
        if "keychain" in secrets_config and sys.platform=="darwin":
            try: backends["keychain"]=KeychainBackend()
            except SecretBackendError: pass
        if "openbao" in secrets_config:
            openbao=secrets_config["openbao"]
            backends["openbao"]=OpenBaoBackend(openbao["base_url"],openbao.get("token_env","OPENBAO_TOKEN"),openbao.get("mount","secret"))
        if "vaultwarden" in secrets_config:
            vaultwarden=secrets_config["vaultwarden"]
            backends["vaultwarden"]=VaultwardenBackend(vaultwarden.get("session_env","BW_SESSION") if isinstance(vaultwarden,dict) else "BW_SESSION")
        return backends

    def _build_auth_manager(self) -> AuthManager:
        auth_config=self.config.get("auth",{})
        manager=AuthManager(auth_config,self.actors)
        openpower_config=auth_config.get("openpower")
        if openpower_config and openpower_config.get("enabled",True):
            from .auth_openpower import OpenPowerAuthProvider
            provider=OpenPowerAuthProvider(
                openpower_config["endpoint"],openpower_config.get("shared_secret_env","OPENPOWER_SHARED_SECRET"),
                issuer=openpower_config.get("issuer","openpower.one"),audience=openpower_config.get("audience","axp"),
                allow_offline=manager.allow_local_fallback,
            )
            manager.register("openpower",provider)
        return manager

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
        self.actions.register(RegisteredAction("resource.list","List/filter APX resources",self.resource_list,obj({"kind":string,"group":string,"tag":string})))
        self.actions.register(RegisteredAction("actor.whoami","Describe an actor and its assigned roles",self.whoami,obj({"subject":string})))
        self.actions.register(RegisteredAction("policy.explain","Explain why an action would be allowed or denied for an actor",self.policy_explain,obj({"subject":string,"requested_action":string,"scope":{"type":"object"}},("subject","requested_action"))))
        self.actions.register(RegisteredAction("state.show","Show current system/security state and history",self.state_show,obj({})))
        self.actions.register(RegisteredAction("state.set","Change system/security state",self.state_set,obj({"name":string,"reason":string,"changed_by":string},("name",)),False,False))
        self.actions.register(RegisteredAction("security.break_glass","Activate temporary emergency access for the current process",self.break_glass,obj({"reason":string,"requested_by":string},("reason",)),False,False))
        self.actions.register(RegisteredAction("secret.get","Read masked secret metadata (never the value)",lambda id:self.secrets.get(id),obj({"id":string},("id",))))
        self.actions.register(RegisteredAction("secret.health","Report secret backend availability and lifecycle state",lambda id:self.secrets.health(id),obj({"id":string},("id",))))
        self.actions.register(RegisteredAction("secret.set","Set a secret value (never echoed back)",lambda id,value:self.secrets.set(id,value),obj({"id":string,"value":string},("id","value")),False,False))
        self.actions.register(RegisteredAction("secret.reveal","Reveal a secret's raw value; requires explicit secret.reveal permission",lambda id:self.secrets.reveal(id),obj({"id":string},("id",))))
        self.actions.register(RegisteredAction("secret.rotate","Run the rotate/verify/activate/test/revoke workflow for a credential; fails clearly until a real provider rotation adapter is configured for that credential",lambda id:self.secrets.rotate(id),obj({"id":string},("id",)),False,False))
        from .docs import generate as _generate_docs
        self.actions.register(RegisteredAction("docs.generate","Generate human/AI/machine documentation for a project from live structured state",lambda project,audience="human":{"audience":audience,"content":_generate_docs(self,project,audience)},obj({"project":string,"audience":string},("project",))))

    def _register_mission_actions(self) -> None:
        obj=lambda properties,required=():{"type":"object","properties":properties,"required":list(required),"additionalProperties":False}
        s={"type":"string"}; arr={"type":"array","items":{"type":"string"}}; a=self.actions.register; R=RegisteredAction
        a(R("mission.list","List Missions, optionally filtered by project/status",self.mission_list,obj({"project":s,"status":s})))
        a(R("mission.inspect","Inspect a Mission",self.mission_inspect,obj({"mission":s},("mission",))))
        a(R("mission.create","Create a Mission describing a desired outcome",self.mission_create,obj({"project":s,"title":s,"objective":s,"description":s,"owner":s,"assigned_agents":arr,"priority":s,"scope":s,"constraints":arr,"success_criteria":arr,"related_resources":arr},("project","title","objective")),False,False))
        a(R("mission.start","Move a Mission to active",lambda mission,changed_by=None:self.missions.set_mission_status(mission,"active",actor=changed_by),obj({"mission":s,"changed_by":s},("mission",)),False,False))
        a(R("mission.block","Move a Mission to blocked",lambda mission,reason="",changed_by=None:self.missions.set_mission_status(mission,"blocked",reason=reason,actor=changed_by),obj({"mission":s,"reason":s,"changed_by":s},("mission",)),False,False))
        a(R("mission.complete","Mark a Mission completed (the actor believes the work is done; not yet verified)",lambda mission,changed_by=None:self.missions.set_mission_status(mission,"completed",actor=changed_by),obj({"mission":s,"changed_by":s},("mission",)),False,False))
        a(R("mission.verify","Verify a Mission's success criteria against evidence/attestation",self.mission_verify,obj({"mission":s,"criteria_met":arr,"verified_by":s},("mission",)),False,False))
        a(R("mission.cancel","Cancel a Mission",lambda mission,reason="",changed_by=None:self.missions.set_mission_status(mission,"cancelled",reason=reason,actor=changed_by),obj({"mission":s,"reason":s,"changed_by":s},("mission",)),False,False))
        a(R("mission.grant","Temporarily grant an actor a scoped permission for the lifetime of this Mission",self.mission_grant,obj({"mission":s,"grantee":s,"action":s,"scope":{"type":"object"}},("mission","grantee","action")),False,False))
        a(R("mission.docs","Generate human/AI/machine Mission status documentation",self.mission_docs,obj({"mission":s,"audience":s},("mission",))))
        a(R("mission.resume","Structured handoff snapshot for a Mission -- lets a new agent resume without prior chat history",self.mission_resume,obj({"mission":s},("mission",))))
        a(R("mission.scope_change.request","Request a meaningful expansion/change of a Mission's scope",self.scope_change_request,obj({"mission":s,"reason":s,"impact":s,"affected_resources":arr,"requested_by":s},("mission","reason","impact")),False,False))
        a(R("mission.scope_change.resolve","Approve, deny, or modify a Mission scope change request",self.scope_change_resolve,obj({"request_id":s,"status":s,"resolution":s,"resolved_by":s},("request_id","status")),False,False))
        a(R("mission_template.list","List built-in and configured Mission templates (workflow shape only)",self.mission_template_list,obj({})))
        a(R("task.list","List Tasks, optionally filtered by mission/status/actor",self.task_list,obj({"mission":s,"status":s,"assigned_actor":s})))
        a(R("task.inspect","Inspect a Task",self.task_inspect,obj({"task":s},("task",))))
        a(R("task.propose","Store an agent-derived list of proposed Tasks for a Mission",self.task_propose,obj({"mission":s,"proposals":{"type":"array","items":{"type":"object"}}},("mission","proposals")),False,False))
        a(R("task.create","Create a single Task; `reason` must explain its relationship to the Mission",self.task_create,obj({"mission":s,"title":s,"reason":s,"objective":s,"assigned_actor":s,"dependencies":arr,"related_resources":arr,"required_actions":arr,"acceptance_criteria":arr,"recommended_prompts":arr},("mission","title","reason")),False,False))
        a(R("task.start","Move a Task to active (fails if dependencies are unmet); reports resource conflicts advisorily",self.task_start,obj({"task":s,"changed_by":s},("task",)),False,False))
        a(R("task.block","Move a Task to blocked",lambda task,reason="",changed_by=None:self.missions.set_task_status(task,"blocked",reason=reason,actor=changed_by),obj({"task":s,"reason":s,"changed_by":s},("task",)),False,False))
        a(R("task.complete","Mark a Task completed (fails while unresolved blockers exist)",lambda task,changed_by=None:self.missions.set_task_status(task,"completed",actor=changed_by),obj({"task":s,"changed_by":s},("task",)),False,False))
        a(R("task.verify","Verify a Task's acceptance criteria against evidence/attestation",self.task_verify,obj({"task":s,"criteria_met":arr,"verified_by":s},("task",)),False,False))
        a(R("task.cancel","Cancel a Task",lambda task,reason="",changed_by=None:self.missions.set_task_status(task,"cancelled",reason=reason,actor=changed_by),obj({"task":s,"reason":s,"changed_by":s},("task",)),False,False))
        a(R("task.claim","Claim a Task so other actors can see it's owned",lambda task,claimant:self.missions.claim_task(task,claimant),obj({"task":s,"claimant":s},("task","claimant")),False,False))
        a(R("task.release","Release a claimed Task",lambda task,claimant:self.missions.release_task(task,claimant),obj({"task":s,"claimant":s},("task","claimant")),False,False))
        a(R("finding.create","Record something discovered while working; does not itself create a Task",lambda mission,summary,task=None,category="informational",reported_by=None:self.missions.add_finding(mission,summary,task=task,category=category,reported_by=reported_by),obj({"mission":s,"summary":s,"task":s,"category":s,"reported_by":s},("mission","summary")),False,False))
        a(R("decision.record","Record a durable decision so future agents don't revisit settled questions",lambda subject,decision,reason,recorded_by=None,mission=None,project=None,affected_resources=None,evidence=None:self.missions.record_decision(subject,decision,reason,actor=recorded_by,mission=mission,project=project,affected_resources=affected_resources,evidence=evidence),obj({"subject":s,"decision":s,"reason":s,"recorded_by":s,"mission":s,"project":s,"affected_resources":arr,"evidence":s},("subject","decision","reason")),False,False))
        a(R("blocker.create","Record something blocking a Mission/Task from proceeding",lambda mission,kind,description,task=None:self.missions.add_blocker(mission,kind,description,task=task),obj({"mission":s,"kind":s,"description":s,"task":s},("mission","kind","description")),False,False))
        a(R("blocker.resolve","Resolve a Blocker",lambda blocker,resolution,resolved_by=None:self.missions.resolve_blocker(blocker,resolution,actor=resolved_by),obj({"blocker":s,"resolution":s,"resolved_by":s},("blocker","resolution")),False,False))
        a(R("evidence.attach","Attach evidence that a Task's work actually happened/succeeded",lambda task,kind,summary,reference=None,attached_by=None:self.missions.attach_evidence(task,kind,summary,reference=reference,attached_by=attached_by),obj({"task":s,"kind":s,"summary":s,"reference":s,"attached_by":s},("task","kind","summary")),False,False))
        a(R("work.current","What is this actor currently supposed to be doing, and why -- scoped context, not the whole environment",self.work_current,obj({"subject":s})))

    def _register_identity_actions(self) -> None:
        obj=lambda properties,required=():{"type":"object","properties":properties,"required":list(required),"additionalProperties":False}
        s={"type":"string"}; arr={"type":"array","items":{"type":"string"}}; a=self.actions.register; R=RegisteredAction
        a(R("auth.status","Report configured authentication providers and enrollment mode",self.auth_status,obj({})))
        a(R("auth.authenticate","Authenticate credentials via a configured provider (local/openpower/...), returning an AuthContext",self.auth_authenticate,obj({"method":s,"credentials":{"type":"object"}},("method",))))
        a(R("identity.inspect","Inspect a Principal (Actor) and its profile",self.identity_inspect,obj({"subject":s},("subject",))))
        a(R("identity.list","List all declared Principals",self.identity_list,obj({})))
        a(R("identity.link","Link a local identity to an OpenPower subject id (metadata only, never a password/token)",self.identity_link,obj({"subject":s,"openpower_subject":s,"linked_by":s},("subject","openpower_subject")),False,False))
        a(R("identity.unlink","Remove a local identity's OpenPower link",self.identity_unlink,obj({"subject":s,"unlinked_by":s},("subject",)),False,False))
        a(R("identity.enrollment.request","Request an identity for an agent/machine (subject to the configured enrollment mode)",self.identity_enrollment_request,obj({"machine_id":s,"runtime":s,"principal":s,"requested_roles":arr,"requested_scopes":arr,"device_fingerprint":s},("machine_id","runtime")),False,False))
        a(R("identity.enrollment.status","Inspect an enrollment request",self.identity_enrollment_status,obj({"request_id":s},("request_id",))))
        a(R("identity.enrollment.cancel","Cancel a pending enrollment request",self.identity_enrollment_cancel,obj({"request_id":s,"cancelled_by":s},("request_id",)),False,False))
        a(R("identity.enrollment.approve","Approve a pending enrollment request",self.identity_enrollment_approve,obj({"request_id":s,"approved_by":s,"openpower_ref":s},("request_id",)),False,False))
        a(R("identity.enrollment.deny","Deny a pending enrollment request",self.identity_enrollment_deny,obj({"request_id":s,"denied_by":s},("request_id",)),False,False))
        a(R("identity.pairing.create","Create a one-time device pairing code (short-lived, process-lifetime only)",self.pairing_create,obj({"ttl_seconds":{"type":"integer"}})))
        a(R("identity.pairing.claim","Claim a one-time device pairing code",self.pairing_claim,obj({"code":s,"claimant":s},("code","claimant")),False,False))
        a(R("credential.issue","Issue a new ActorCredential (metadata + fingerprint only; never a raw secret)",self.credential_issue,obj({"principal":s,"type":s,"issuer":s,"expires":s,"fingerprint":s,"secret_ref":s},("principal",)),False,False))
        a(R("credential.inspect","Inspect an ActorCredential's lifecycle state",self.credential_inspect,obj({"credential_id":s},("credential_id",))))
        a(R("credential.rotate","Issue a replacement ActorCredential; the old one is marked rotating, not yet revoked",self.credential_rotate,obj({"credential_id":s,"fingerprint":s,"secret_ref":s},("credential_id",)),False,False))
        a(R("credential.confirm_rotation","Confirm the replacement credential works; only then is the old one revoked",self.credential_confirm_rotation,obj({"previous_credential_id":s},("previous_credential_id",)),False,False))
        a(R("credential.revoke","Revoke an ActorCredential immediately",self.credential_revoke,obj({"credential_id":s,"revoked_by":s},("credential_id",)),False,False))

    def _load_connections(self) -> None:
        for value in self.config.get("connections",[]):
            connection=Connection(value["id"],value["adapter"],value.get("resource"),value.get("credential"),{k:v for k,v in value.items() if k not in {"id","adapter","resource","credential"}})
            self.connections.append(connection)
            if connection.adapter=="mcp_stdio": self._register_mcp_stdio_connection(connection)
            else: self.connection_health.append({"id":connection.id,"adapter":connection.adapter,"ok":False,"error":"adapter is not configured by the core"})

    def _register_mcp_stdio_connection(self, connection: Connection) -> dict[str,Any]:
        """Spawns the MCP server, registers each of its tools as a normal apx Action
        namespaced `<connection.id>.<tool>`, and returns a connection_health-shaped
        result -- shared by static `[[connections]]` config (_load_connections) and
        `environment.ingest` (dynamically discovered connections), so a tool
        registered either way behaves identically to every caller."""
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
            result={"id":connection.id,"adapter":connection.adapter,"ok":True,"capabilities":len(tools)}
        except Exception as error: result={"id":connection.id,"adapter":connection.adapter,"ok":False,"error":str(error)}
        self.connection_health.append(result)
        return result

    def _register_environment_ingest_actions(self) -> None:
        obj=lambda properties,required=():{"type":"object","properties":properties,"required":list(required),"additionalProperties":False}
        s={"type":"string"}
        self.actions.register(RegisteredAction(
            "environment.sources","Information: known dotfile/config sources apx can ingest MCP servers from, whether each is enabled, and what's actually found on disk -- read-only, never spawns anything",
            self.environment_sources,obj({})))
        self.actions.register(RegisteredAction(
            "environment.ingest","Import an enabled source's already-configured MCP servers as live apx Connections/Actions -- spawns each server as a subprocess to introspect its tools",
            self.environment_ingest,obj({"source":s},("source",)),False,False,confirmation="confirm",resource_type="connection"))

    def environment_sources(self) -> dict[str,Any]:
        ingest_config=self.config.get("ingest",{})
        results=[]
        for source_id,source in _environment_ingest.SOURCES.items():
            enabled=bool(ingest_config.get(source_id,{}).get("enabled",False))
            already_ingested=sorted(c.id for c in self.connections if c.id.startswith(f"{source_id}."))
            results.append({"enabled":enabled,"verified":source.verified,"label":source.label,"already_ingested":already_ingested,**source.probe()})
        for source_id in _environment_ingest.PLANNED_SOURCES:
            results.append({"id":source_id,"label":source_id.replace("_"," ").title(),"verified":False,"enabled":False,"status":"planned","found":None})
        return {"sources":results}

    def environment_ingest(self, source: str) -> dict[str,Any]:
        if source in _environment_ingest.PLANNED_SOURCES:
            raise ActionError(f"{source!r} has no verified ingestion support yet (see environment.sources)")
        ingest_source=_environment_ingest.SOURCES.get(source)
        if ingest_source is None:
            raise ActionError(f"unknown ingest source {source!r}; known: {', '.join(sorted(_environment_ingest.SOURCES))}, planned: {', '.join(_environment_ingest.PLANNED_SOURCES)}")
        if not self.config.get("ingest",{}).get(source,{}).get("enabled",False):
            raise ActionError(f"ingest source {source!r} is disabled; enable it first with [ingest.{source}]\\nenabled = true in apx.toml")
        servers=ingest_source.mcp_servers()
        if not servers: return {"source":source,"ingested":[],"message":"no MCP servers found (or the source's config could not be parsed)"}
        results=[]
        for name,server_config in servers.items():
            connection_id=f"{source}.{name}"
            if any(c.id==connection_id for c in self.connections):
                results.append({"name":name,"connection":connection_id,"skipped":"already ingested"}); continue
            connection=Connection(connection_id,"mcp_stdio",None,None,{"command":[server_config["command"],*server_config["args"]]})
            self.connections.append(connection)
            outcome=self._register_mcp_stdio_connection(connection)
            results.append({"name":name,"connection":connection_id,**outcome})
        return {"source":source,"ingested":results}

    def run(self, action: str, /, *, actor: str | None = None, target: dict[str, Any] | None = None, auth_context: dict[str, Any] | None = None, confirmation: dict[str, Any] | None = None, **inputs: Any) -> ActionResult:
        derived={key:inputs[key] for key in ("host","service","project","source_host","destination_host","id") if key in inputs and inputs[key] is not None}
        return self.execute(ActionRequest(action=action,target={**derived,**(target or {})},input=inputs,actor=actor,auth_context=auth_context,confirmation=confirmation))

    async def run_async(self, action: str, /, **values: Any) -> ActionResult:
        """Async-friendly SDK surface; deterministic handlers still execute in Python."""
        return await asyncio.to_thread(self.run,action,**values)

    def register_procedure(self, procedure: Procedure) -> RegisteredAction:
        confirmation_rank=self._CONFIRMATION_RANK
        required=max((confirmation_rank[self.actions.get(step.action).confirmation] for step in procedure.steps),default=0)
        if confirmation_rank[procedure.confirmation]<required: raise ValueError("procedure confirmation cannot be weaker than a step")
        self.procedures.register(procedure,{item.name for item in self.actions.list()})
        forwarded=sorted({name for step in procedure.steps for name in step.forward})
        properties={name:{} for name in forwarded}
        action=RegisteredAction(procedure.id,procedure.description,lambda **inputs: inputs,{"type":"object","properties":properties,"required":forwarded,"additionalProperties":False},False,False,risk=procedure.risk,confirmation=procedure.confirmation,provenance="local_component",tags=("procedure",))
        self.actions.register(action); return action

    def _execute_procedure(self, procedure: Procedure, actor: str, inputs: dict[str,Any]) -> dict[str,Any]:
        results=[]
        for index,step in enumerate(procedure.steps):
            definition=self.actions.get(step.action)
            confirmation={"level":definition.confirmation,"confirmed":True,"authorization_id":f"procedure:{procedure.id}:{index}:{time.time_ns()}"} if definition.confirmation!="none" else None
            outcome=self.run(step.action,actor=actor,confirmation=confirmation,**{**step.input,**{name:inputs[name] for name in step.forward}})
            results.append(outcome.compact())
            if not outcome.ok: raise ProcedureFailed(procedure.id,step.action,outcome.error.code if outcome.error else "execution_failed",outcome.error.message if outcome.error else outcome.status)
        return {"procedure":procedure.id,"steps":results,"changed":any(item.get("result",{}).get("changed",False) for item in results if isinstance(item.get("result"),dict)),"reasoning_calls":0}

    def _execute_blueprint(self, action_name: str, actor: str, values: dict[str,Any]) -> dict[str,Any]:
        if action_name=="blueprint.plan": return self.blueprint_plan(actor=actor,**values)
        if action_name=="blueprint.apply": return self.blueprint_apply(actor=actor,**values)
        return self.blueprint_upgrade(actor=actor,**values)

    def _execute_grant(self, action_name: str, actor: str, values: dict[str,Any]) -> dict[str,Any]:
        if action_name=="grant.issue": return self.grant_issue(actor=actor,**values)
        return self.grant_revoke(actor=actor,**values)

    def _execute_agent(self, action_name: str, actor: str, values: dict[str,Any]) -> dict[str,Any]:
        if action_name=="agent.setup": return self.agent_setup(actor=actor,**values)
        return self.agent_remove(actor=actor,**values)

    def execution_metrics(self) -> dict[str,Any]: return self.execution.metrics.snapshot()

    def prepare(self, action: str, /, *, actor: str | None = None, target: dict[str, Any] | None = None, **inputs: Any) -> PreparedAction:
        """Resolves what EXECUTE would do -- exact target, confirmation requirement,
        reversibility -- without doing it. Does not check policy: PREPARE answers
        "what would happen", not "am I allowed" (that's still decided at execute()
        time, same as every other action, so prepare can never be used to probe
        permissions without a real attempt)."""
        derived={key:inputs[key] for key in ("host","service","project","source_host","destination_host","id") if key in inputs and inputs[key] is not None}
        resolved_target={**derived,**(target or {})}
        registered=self.actions.get(action); definition=registered.definition(); values={}
        if registered.prepare_handler:
            raw=registered.prepare_handler(**inputs)
            values=dict(raw) if isinstance(raw,dict) else {}
        prepared=PreparedAction(
            action=definition.id,target=resolved_target,input=inputs,
            effect=values.pop("effect",definition.description),confirmation_required=definition.confirmation,
            reversible=definition.reversible,reverse_action=definition.reverse_action,
            provider=definition.provider,side_effects=definition.side_effects,**values,
        )
        self.emit(Event("action.prepared",definition.provider or "apx",{"action":action,"request":prepared.request_id},{"confirmation":definition.confirmation,"reversible":definition.reversible}))
        return prepared

    def register_provider(self, provider: ActionProvider) -> ProviderManifest:
        if provider.identity.id in self.providers: raise ValueError(f"provider {provider.identity.id!r} is already connected")
        errors=validate_provider(provider)
        if errors: raise ValueError("provider conformance failed: "+"; ".join(errors))
        provider.register(self.actions); self.providers[provider.identity.id]=provider
        self.emit(Event("provider.connected","apx",{"provider":provider.identity.id},{"actions":len(provider.actions)}))
        for action in provider.actions: self.emit(Event("provider.action_added","apx",{"provider":provider.identity.id,"action":action.name},{}))
        return provider.manifest()

    def connect_provider(self, origin: str, *, opener=None) -> ProviderManifest:
        remote=RemoteProvider.discover(origin,opener=opener); manifest=remote.manifest()
        if manifest.provider.id in self.providers: raise ValueError(f"provider {manifest.provider.id!r} is already connected")
        for item in manifest.actions:
            def invoke(_action=item.id,**inputs):
                response=remote.execute_action(ActionRequest(_action,input=inputs,actor=self.actors.resolve_default()))
                if not response.get("ok"): raise ActionError(response.get("error",{}).get("message","remote action failed"))
                return response.get("result")
            self.actions.register(RegisteredAction(item.id,item.description,invoke,item.input_schema,item.read_only,item.destructive,
                output_schema=item.output_schema,risk=item.risk,confirmation=item.confirmation,reversible=item.reversible,
                reverse_action=item.reverse_action,idempotent=item.idempotent,required_permissions=item.required_permissions,
                provider=manifest.provider.id,provenance=item.provenance,tags=item.tags,version=item.version,deprecated=item.deprecated,
                resource_type=item.resource_type,side_effects=item.side_effects,credential_requirements=item.credential_requirements,
                actor_requirements=item.actor_requirements,expected_verification=item.expected_verification,remediation_action=item.remediation_action))
        self.providers[manifest.provider.id]=remote
        self.emit(Event("provider.connected","apx",{"provider":manifest.provider.id},{"origin":origin,"actions":len(manifest.actions)}))
        return manifest

    def provider_manifests(self) -> list[ProviderManifest]: return [provider.manifest() for provider in self.providers.values()]

    def register_bridge(self,bridge) -> None:
        if bridge.id in self.bridges: raise ValueError(f"bridge {bridge.id!r} already registered")
        bridge.register_actions(self.actions); self.bridges[bridge.id]=bridge

    def capability_graph(self, actor: str | None = None) -> CapabilityGraph:
        """actor=None returns the full, unfiltered graph (an operator/admin view).
        actor=<id> returns only what that actor could currently discover -- the same
        predicate APX.discover() and MCPServer.tools() use, so "what can I do" never
        has a different answer depending on which surface asked."""
        graph=CapabilityGraph()
        resources=self.resources()
        for resource in resources: graph.add_resource(resource)
        for action in self.actions.list():
            if actor is None or self._actor_can_discover(actor,action.name):
                graph.add_action(action.definition())
        # Existing discovered host capabilities remain first-class even when they do
        # not map to an invokable Action yet.
        for host in self.hosts:
            for capability in self.capabilities(host):
                if capability.resource in graph.resources: graph.add_capability(capability)
        for provider in self.providers.values():
            manifest=provider.manifest()
            for resource in manifest.resources:
                for action in manifest.actions:
                    if not action.resource_type or action.resource_type==resource.kind:
                        key=f"{resource.id}:{action.resource_type or 'actions'}"
                        existing=graph.capabilities.get(key)
                        actions=tuple(sorted(set((existing.actions if existing else ())+ (action.id,))))
                        graph.capabilities[key]=Capability(action.resource_type or "actions",resource.id,actions=actions,
                            provenance=action.provenance,reliability=1.0,source=manifest.provider.id)
        for bridge in self.bridges.values(): graph.add_bridge(bridge)
        return graph

    def provider_actor(self, request: ActionRequest) -> ActorDescriptor:
        actor=request.actor or self.actors.resolve_default(); profile=self.actors.get(actor)
        return ActorDescriptor(actor.split(":",1)[0],actor,owner=request.delegated_by,client=request.client,device=request.device,
            roles=tuple(profile.roles if profile else ()),delegated_by=request.delegated_by,permissions=(request.action,))

    # Always answerable regardless of the caller's own permissions -- "why was this denied?"
    # must never itself be deniable, or permission failures become mysterious. auth.authenticate
    # is included for the same reason from the other direction: proving who you are cannot
    # itself require a permission grant, or the system is circular and unusable from cold start.
    INTROSPECTION_ACTIONS = frozenset({"actor.whoami","policy.explain","state.show","auth.authenticate","discovery.capabilities"})

    def _mission_extra_allow(self, actor: str) -> tuple[ScopedRule, ...]:
        return tuple(ScopedRule(g["action"],{k:scope_values(v) for k,v in g.get("scope",{}).items()}) for g in self.missions.active_grants(actor))

    # Resource kinds PolicyEngine already knows how to match against an action's
    # derived target (see policy._match_scope and run()'s `derived` dict) -- a Grant
    # scoped to an apx://host/x or apx://project/x ref binds through the exact same
    # scope dimension a static role rule would use for that resource kind. Any other
    # kind falls back to a generic "resource" dimension, which only binds if the
    # invoked action's own target happens to carry a matching "resource" key.
    _GRANT_RESOURCE_KIND_TO_SCOPE_DIMENSION = {"host": "host", "node": "host", "project": "project"}

    def _grant_extra_allow(self, actor: str) -> tuple[ScopedRule, ...]:
        rules=[]
        for grant in self.grants.active_for(actor):
            scope: dict[str, list[str]] = {k: list(scope_values(v)) for k, v in grant.constraints.items()}
            for ref in grant.resources:
                try: kind, resource_id = parse_resource_ref(ref)
                except ValueError: continue
                dimension = self._GRANT_RESOURCE_KIND_TO_SCOPE_DIMENSION.get(kind, "resource")
                scope.setdefault(dimension, []).append(resource_id)
            rules.extend(ScopedRule(pattern,{k: scope_values(v) for k,v in scope.items()}) for pattern in grant.actions)
        return tuple(rules)

    def _extra_allow(self, actor: str) -> tuple[ScopedRule, ...]:
        """Every source of delegated (non-role) authority a request may draw on --
        Mission-scoped grants and standalone Grants alike. A single combined tuple so
        policy evaluation and discovery filtering never drift out of sync with each other."""
        return self._mission_extra_allow(actor)+self._grant_extra_allow(actor)

    def _actor_can_discover(self, actor: str, action_name: str) -> bool:
        """Coarse discovery-time visibility check -- the single predicate every
        discovery surface (APX.discover(), MCPServer.tools(), capability_graph())
        shares, so there is exactly one definition of "can this actor see this
        capability", not one for the UI/API and a different one for AI. Not
        authoritative; execute() still evaluates policy in full at invocation time.
        Introspection actions (see INTROSPECTION_ACTIONS) are always discoverable,
        same as they're always invokable -- a caller must always be able to find out
        what it itself can do."""
        return action_name in self.INTROSPECTION_ACTIONS or self.policy.might_allow(actor,action_name,self._extra_allow(actor))

    def discover(self, subject: str | None = None, *, namespaces: tuple[str,...] = (), compact: bool = True) -> dict[str, Any]:
        """The DISCOVER protocol operation: identity-aware, policy-filtered capability
        listing. available = service capabilities intersected with the requesting
        subject's role/grant authority -- an actor never sees an action discovery
        wouldn't let it attempt."""
        subject_id=subject or self.actors.resolve_default()
        predicate=lambda action: self._actor_can_discover(subject_id,action.name)
        return {"apx":APX_PROTOCOL_VERSION,"subject":subject_id,
                "capabilities":self.actions.describe(namespaces=namespaces,predicate=predicate,compact=compact)}

    def execute(self, request: ActionRequest) -> ActionResult:
        actor=request.actor or self.actors.resolve_default()
        # Authentication informs policy of *who* is asking; it never grants authority --
        # PolicyEngine below still only ever consults the local actor-id -> role mapping,
        # regardless of authentication_method (local_os/openpower/cached_openpower/...).
        auth_context=request.auth_context or self.auth.default_context(actor).to_dict()
        if request.action in self.INTROSPECTION_ACTIONS:
            decision=PolicyDecision(True,actor,request.action,"introspection action; always answerable",None)
        else:
            decision=self.policy.evaluate(actor,request.action,request.target,self.state.get(),self._extra_allow(actor))
        self.emit(Event(name="policy.allowed" if decision.allowed else "policy.denied",source="apx",subject={"actor":actor,"action":request.action,"delegated_by":auth_context.get("delegated_by")},data={"reason":decision.reason,"scope":decision.scope,"authentication_method":auth_context.get("authentication_method")},correlation_id=request.request_id))
        if not decision.allowed:
            result=ActionResult(action=request.action,ok=False,error=StructuredError("permission_denied",decision.reason),request_id=request.request_id,target=request.target)
            return result
        if request.action in ("mission.grant","grant.issue"):
            # An actor may only delegate a permission it already holds itself -- otherwise
            # `mission.*`/`grant.*` alone would let any actor grant itself/anyone anything,
            # including secret.reveal, with no relationship to what it's actually allowed to do.
            # grant.issue's own scope lives in its `resources` input (apx://kind/id refs), not
            # in request.target -- run()'s target-derivation only recognizes host/service/
            # project/etc. as top-level kwargs, which `resources` is not. Without folding
            # `resources` in here, this check evaluates against an empty target and wrongly
            # concludes a granter scoped to e.g. host=web1 holds nothing at all.
            self_check_target=dict(request.target or {})
            if request.action=="grant.issue":
                for resource_ref_value in request.input.get("resources") or ():
                    try: kind,resource_id=parse_resource_ref(resource_ref_value)
                    except ValueError: continue
                    self_check_target.setdefault(kind,resource_id)
            granted_actions=[request.input.get("action")] if request.action=="mission.grant" else list(request.input.get("actions") or ())
            for granted_action in granted_actions:
                grant_decision=self.policy.evaluate(actor,granted_action,self_check_target,self.state.get(),self._extra_allow(actor))
                if not grant_decision.allowed: break
            else: grant_decision=None
            if grant_decision is not None and not grant_decision.allowed:
                reason=f"cannot grant {granted_action!r}: granter does not hold that permission ({grant_decision.reason})"
                result=ActionResult(action=request.action,ok=False,error=StructuredError("permission_denied",reason),request_id=request.request_id,target=request.target)
                return result
        try:
            definition = self.actions.get(request.action)
        except ActionError as error:
            result=ActionResult(action=request.action,ok=False,error=StructuredError("action.not_found",str(error)),request_id=request.request_id,target=request.target,status="failed")
            self._emit_for_result(request,result)
            return result
        if request.expires_at:
            try: expired=datetime.fromisoformat(request.expires_at.replace("Z","+00:00"))<=datetime.now(timezone.utc)
            except ValueError: expired=True
            if expired: return ActionResult(request.action,False,error=StructuredError("request_expired","action request has expired"),request_id=request.request_id,target=request.target,status="failed")
        if request.credential and request.credential.revoked:
            return ActionResult(request.action,False,error=StructuredError("credential_revoked","actor credential is revoked"),request_id=request.request_id,target=request.target,status="failed")
        if definition.provider and definition._risk()!="read" and request.auth_context is None:
            return ActionResult(request.action,False,error=StructuredError("authentication_required","consequential provider action requires authenticated actor context"),request_id=request.request_id,target=request.target,status="authorization_required")
        effective_input={key:value for key,value in request.input.items() if value is not None or key in definition.schema.get("required",())}
        try: Draft202012Validator(definition.schema).validate(effective_input)
        except ValidationError as error:
            path=list(error.absolute_path)
            message=f"input at {'.'.join(map(str,path)) or '<root>'} failed JSON Schema rule {error.validator}"
            if error.validator=="additionalProperties":
                unexpected=sorted(set(effective_input)-set(definition.schema.get("properties",{})))
                if unexpected: message+=f" (unexpected fields: {', '.join(unexpected)})"
            return ActionResult(request.action,False,error=StructuredError("invalid_input",message,{"path":path,"rule":error.validator}),request_id=request.request_id,target=request.target,status="failed")
        # Confirmation gate: opt-in per action (definition.confirmation defaults to "none",
        # see RegisteredAction) so this can never retroactively block an existing action
        # nothing has started sending confirmation for. A supplied confirmation must name
        # the exact level the action requires -- "confirm" doesn't satisfy "transaction".
        required=definition.confirmation
        supplied=(request.confirmation or {}) if required!="none" else {}
        authorization_id=supplied.get("authorization_id") or supplied.get("nonce")
        valid=required=="none" or (required=="delegated" and bool(request.delegated_by)) or (supplied.get("level")==required and supplied.get("confirmed") is True)
        if supplied.get("expires_at"):
            try: valid=valid and datetime.fromisoformat(supplied["expires_at"].replace("Z","+00:00"))>datetime.now(timezone.utc)
            except ValueError: valid=False
        if authorization_id and authorization_id in self._used_authorizations: valid=False
        if required=="transaction":
            prepared=self.prepare(request.action,actor=actor,target=request.target,**request.input)
            valid=valid and supplied.get("terms")==prepared.confirmation_terms
        if not valid:
            result=ActionResult(
                action=request.action,ok=False,request_id=request.request_id,target=request.target,
                status="authorization_required",
                result={"authorization":{"method":"provider","requested_confirmation":required,"action_request_id":request.request_id,
                    "authorization_url":supplied.get("authorization_url"),"expires_at":supplied.get("expires_at")}},
                error=StructuredError("authorization_required",f"{required} confirmation is required"),
            )
            self.emit(Event(name="action.authorization_required",source="apx",subject={"actor":actor,"action":request.action},data={"required_confirmation":required},correlation_id=request.request_id))
            return result
        if authorization_id: self._used_authorizations.add(authorization_id)
        if required!="none": self.emit(Event("action.authorized",definition.provider or "apx",{"actor":actor,"action":request.action},{"confirmation":required},correlation_id=request.request_id))
        try:
            self.emit(Event("action.started",definition.provider or "apx",{"actor":actor,"action":request.action},{},correlation_id=request.request_id))
            if "procedure" in definition.tags:
                procedure=self.procedures.get(definition.name)
                raw,execution=self.execution.run(replace(definition,handler=lambda **values:self._execute_procedure(procedure,actor,values)),effective_input)
            elif "blueprint" in definition.tags:
                raw,execution=self.execution.run(replace(definition,handler=lambda _name=definition.name,**values:self._execute_blueprint(_name,actor,values)),effective_input)
            elif "grant" in definition.tags:
                raw,execution=self.execution.run(replace(definition,handler=lambda _name=definition.name,**values:self._execute_grant(_name,actor,values)),effective_input)
            elif "agent" in definition.tags:
                raw,execution=self.execution.run(replace(definition,handler=lambda _name=definition.name,**values:self._execute_agent(_name,actor,values)),effective_input)
            else: raw,execution = self.execution.run(definition,effective_input)
            # secret.reveal is the one sanctioned path for a raw value; policy already gated it above.
            data = raw if request.action=="secret.reveal" else self.credentials.redact(raw)
            if definition.output_schema is not None: Draft202012Validator(definition.output_schema).validate(data)
            verification="unverified"
            if definition.verify_handler: verification="verified" if definition.verify_handler(data,**effective_input) else "failed"
            elif definition.read_only: verification="not_applicable"
            receipt=None
            if definition.provider or required!="none" or definition.destructive:
                from .crypto import sign_receipt_dict
                raw_dict = {
                    "action": definition.name, "provider": definition.provider, "target": request.target,
                    "actor": actor, "status": "completed", "result": data, "request_id": request.request_id,
                    "verification_status": verification, "reversible": definition.reversible,
                    "reverse_action": definition.reverse_action, "side_effects": tuple(definition.side_effects),
                    "reversal": {"available": definition.reversible, "action": definition.reverse_action} if definition.reversible else {"available": False, "remediation_action": definition.remediation_action}
                }
                signed = sign_receipt_dict(raw_dict, node_name=getattr(self, "node_name", "local"))
                receipt = ActionReceipt(
                    action=signed["action"], provider=signed.get("provider"), target=signed.get("target", {}),
                    actor=signed.get("actor"), status=signed.get("status", "completed"), result=signed.get("result"),
                    request_id=signed.get("request_id"), verification_status=signed.get("verification_status", "unverified"),
                    reversible=signed.get("reversible", False), reverse_action=signed.get("reverse_action"),
                    side_effects=tuple(signed.get("side_effects", ())), reversal=signed.get("reversal"),
                    digest=signed.get("digest"), signature=signed.get("signature"), signer_node=signed.get("signer_node"), key_id=signed.get("key_id")
                )
                provider=self.providers.get(definition.provider or "")
                if isinstance(provider,ActionProvider): provider.receipts[receipt.receipt_id]=receipt
            result=ActionResult(action=definition.name,ok=True,result=data,request_id=request.request_id,target=request.target,status="completed",receipt=receipt,execution=execution.to_dict())
            self._emit_for_result(request,result)
            return result
        except ReasoningRequired as error:
            result=ActionResult(action=request.action,ok=False,error=StructuredError("reasoning_required",str(error),error.context),request_id=request.request_id,target=request.target,status="failed",needs_reasoning=True,execution={"deterministic":True,"status":"needs_reasoning","reasoning_calls":0,"model_calls_avoided":0})
            self._emit_for_result(request,result); return result
        except ProcedureFailed as error:
            result=ActionResult(action=request.action,ok=False,error=StructuredError(error.code,str(error),{"procedure":error.procedure,"step":error.step}),request_id=request.request_id,target=request.target,status="failed")
            self._emit_for_result(request,result); return result
        except (ActionError, RuntimeError, OSError, ValueError, TypeError) as error:
            # TypeError included: an unexpected/misspelled/missing input field is a caller
            # mistake (CLI/MCP/Python/agent), not a crash -- every actor gets a structured
            # action.failed instead of an uncaught traceback, at this one execution point.
            code="action.not_found" if "unknown action" in str(error) else "action.failed"
            result=ActionResult(action=request.action,ok=False,error=StructuredError(code,self.credentials.redact_text(str(error))),request_id=request.request_id,target=request.target,status="failed")
            self._emit_for_result(request,result)
            return result

    def whoami(self, subject: str | None = None) -> dict[str, Any]:
        actor_id=subject or self.actors.resolve_default(); profile=self.actors.get(actor_id)
        return {"actor":actor_id,"roles":list(self.policy.roles_for(actor_id)),"known":profile is not None,"profile":profile.to_dict() if profile else None}

    def policy_explain(self, subject: str, requested_action: str, scope: dict[str, Any] | None = None) -> dict[str, Any]:
        return self.policy.explain(subject,requested_action,scope or {},self.state.get(),self._extra_allow(subject)).to_dict()

    def state_show(self) -> dict[str, Any]: return self.state.status()

    def state_set(self, name: str, reason: str = "", changed_by: str | None = None) -> dict[str, Any]:
        actor_id=changed_by or self.actors.resolve_default(); entry=self.state.set(name,reason,actor_id)
        self.emit(Event("system.state_changed","apx",{"state":name},{"from":entry["from"],"to":name,"reason":reason,"actor":actor_id}))
        if name in SECURITY_STATES: self.emit(Event(f"security.{name}_started","apx",{"state":name},{"reason":reason,"actor":actor_id}))
        elif entry["from"]=="lockdown": self.emit(Event("security.lockdown_ended","apx",{"state":name},{"reason":reason,"actor":actor_id}))
        return entry

    def break_glass(self, reason: str, requested_by: str | None = None) -> dict[str, Any]:
        actor_id=requested_by or self.actors.resolve_default(); event=self.emit(Event("security.break_glass_started","apx",{"actor":actor_id},{"reason":reason}))
        return {"actor":actor_id,"reason":reason,"activated_at":event.occurred_at}

    # ---- Blueprint handler methods ----

    def blueprint_list(self, category: str | None = None, tag: str | None = None) -> dict[str, Any]:
        return {"blueprints": self.blueprint_registry.search("", category=category, tag=tag)}

    def blueprint_search(self, query: str = "", category: str | None = None, tag: str | None = None) -> dict[str, Any]:
        return {"blueprints": self.blueprint_registry.search(query, category=category, tag=tag)}

    def blueprint_show(self, blueprint: str, version: str | None = None) -> dict[str, Any]:
        try: return self.blueprint_registry.resolve(blueprint, version).to_dict()
        except BlueprintError as error: raise ActionError(str(error)) from error

    def blueprint_status(self, project: str) -> dict[str, Any]:
        if project not in self.projects: raise ActionError(f"unknown project {project!r}")
        return {"project": project, "applied": self.blueprints.applied(project),
                "capabilities": self.blueprints.capabilities(project), "history": self.blueprints.history(project)}

    def blueprint_plan(self, actor: str, blueprint: str, version: str | None = None, project: str | None = None, inputs: dict[str, Any] | None = None) -> dict[str, Any]:
        if project is not None and project not in self.projects: raise ActionError(f"unknown project {project!r}")
        try:
            resolved = self.blueprint_registry.resolve(blueprint, version)
            return _run_blueprint_plan(self, resolved, actor=actor, project=project, inputs=inputs)
        except BlueprintError as error: raise ActionError(str(error)) from error

    def blueprint_apply(self, actor: str, blueprint: str, version: str | None = None, project: str | None = None, inputs: dict[str, Any] | None = None) -> dict[str, Any]:
        if project is not None and project not in self.projects: raise ActionError(f"unknown project {project!r}")
        try:
            resolved = self.blueprint_registry.resolve(blueprint, version)
            return _run_blueprint_apply(self, resolved, actor=actor, project=project, inputs=inputs)
        except BlueprintError as error: raise ActionError(str(error)) from error

    def blueprint_upgrade(self, actor: str, blueprint: str, project: str, inputs: dict[str, Any] | None = None) -> dict[str, Any]:
        if project not in self.projects: raise ActionError(f"unknown project {project!r}")
        try: resolved = self.blueprint_registry.resolve(blueprint)
        except BlueprintError as error: raise ActionError(str(error)) from error
        previous = self.blueprints.applied(project).get(resolved.name)
        if previous and previous["version"] == resolved.version:
            return {"blueprint": resolved.name, "version": resolved.version, "already_current": True, "previous_version": previous["version"]}
        result = _run_blueprint_apply(self, resolved, actor=actor, project=project, inputs=inputs)
        result["previous_version"] = previous["version"] if previous else None
        result["upgraded"] = True
        return result

    # ---- Grant handler methods ----

    def grant_issue(self, actor: str, subject: str, actions: list[str], resources: list[str] | None = None,
                     constraints: dict[str, Any] | None = None, reason: str = "", expires_at: str | None = None) -> dict[str, Any]:
        grant = self.grants.issue(subject, actor, tuple(actions), resources=tuple(resources or ()),
                                   constraints=constraints, reason=reason, expires_at=expires_at)
        return grant.to_dict()

    def grant_list(self, subject: str | None = None, include_expired: bool = False) -> dict[str, Any]:
        return {"grants": [g.to_dict() for g in self.grants.list(subject=subject, include_expired=include_expired)]}

    def grant_inspect(self, grant: str) -> dict[str, Any]:
        try: return self.grants.get(grant).to_dict()
        except GrantError as error: raise ActionError(str(error)) from error

    def grant_revoke(self, actor: str, grant: str) -> dict[str, Any]:
        try: return self.grants.revoke(grant, revoked_by=actor).to_dict()
        except GrantError as error: raise ActionError(str(error)) from error

    # ---- Mission / Task / Work handler methods ----

    def mission_list(self, project: str | None = None, status: str | None = None) -> dict[str, Any]:
        return {"missions": self.missions.list_missions(project, status)}

    def mission_inspect(self, mission: str) -> dict[str, Any]:
        try: return self.missions.get_mission(mission)
        except MissionError as error: raise ActionError(str(error)) from error

    def mission_create(self, project: str, title: str, objective: str, **fields: Any) -> dict[str, Any]:
        if project not in self.projects: raise ActionError(f"unknown project {project!r}")
        return self.missions.create_mission(project, title, objective, **fields)

    def mission_verify(self, mission: str, criteria_met: list[str] | None = None, verified_by: str | None = None) -> dict[str, Any]:
        try: return self.missions.verify_mission(mission, criteria_met=criteria_met, actor=verified_by)
        except MissionError as error: raise ActionError(str(error)) from error

    def mission_grant(self, mission: str, grantee: str, action: str, scope: dict[str, Any] | None = None) -> dict[str, Any]:
        try: return self.missions.grant_permission(mission, grantee, action, scope)
        except MissionError as error: raise ActionError(str(error)) from error

    def mission_docs(self, mission: str, audience: str = "human") -> dict[str, Any]:
        from .docs import generate_mission as _generate_mission_docs
        return {"audience": audience, "content": _generate_mission_docs(self, mission, audience)}

    def mission_resume(self, mission: str) -> dict[str, Any]:
        try: return self.missions.resume(mission)
        except MissionError as error: raise ActionError(str(error)) from error

    def mission_template_list(self) -> dict[str, Any]:
        from .missions import templates as _mission_templates
        return {"templates": _mission_templates(self)}

    def scope_change_request(self, mission: str, reason: str, impact: str, affected_resources: list[str] | None = None, requested_by: str | None = None) -> dict[str, Any]:
        try:
            request = self.missions.request_scope_change(mission, requested_by or self.actors.resolve_default(), reason, impact, affected_resources=affected_resources)
        except MissionError as error: raise ActionError(str(error)) from error
        self.emit(Event("mission.scope_change_requested", "apx", {"mission": mission}, {"request": request["id"], "reason": reason}))
        return request

    def scope_change_resolve(self, request_id: str, status: str, resolution: str = "", resolved_by: str | None = None) -> dict[str, Any]:
        try: return self.missions.resolve_scope_change(request_id, status, resolution=resolution, actor=resolved_by)
        except MissionError as error: raise ActionError(str(error)) from error

    def task_list(self, mission: str | None = None, status: str | None = None, assigned_actor: str | None = None) -> dict[str, Any]:
        return {"tasks": self.missions.list_tasks(mission, status, assigned_actor)}

    def task_inspect(self, task: str) -> dict[str, Any]:
        try: return self.missions.get_task(task)
        except MissionError as error: raise ActionError(str(error)) from error

    def task_propose(self, mission: str, proposals: list[dict[str, Any]]) -> dict[str, Any]:
        try: return {"tasks": self.missions.propose_tasks(mission, proposals)}
        except (MissionError, TypeError) as error: raise ActionError(str(error)) from error

    def task_create(self, mission: str, title: str, reason: str, **fields: Any) -> dict[str, Any]:
        try: return self.missions.create_task(mission, title, reason, **fields)
        except MissionError as error: raise ActionError(str(error)) from error

    def task_start(self, task: str, changed_by: str | None = None) -> dict[str, Any]:
        try:
            record = self.missions.set_task_status(task, "active", actor=changed_by)
            conflicts = self.missions.detect_conflicts(task)
        except MissionError as error: raise ActionError(str(error)) from error
        return {**record, "conflicts": conflicts}

    def task_verify(self, task: str, criteria_met: list[str] | None = None, verified_by: str | None = None) -> dict[str, Any]:
        try: return self.missions.verify_task(task, criteria_met=criteria_met, actor=verified_by)
        except MissionError as error: raise ActionError(str(error)) from error

    def work_current(self, subject: str | None = None) -> dict[str, Any]:
        actor_id = subject or self.actors.resolve_default()
        task = self.missions.current_for_actor(actor_id)
        if not task: return {"actor": actor_id, "task": None, "mission": None, "note": "no active/blocked Task is currently claimed by or assigned to this actor"}
        mission = self.missions.get_mission(task["mission"])
        return {
            "actor": actor_id, "mission": mission, "task": task,
            "reason": task["reason"], "constraints": mission["constraints"], "success_criteria": task["acceptance_criteria"],
            "related_resources": task["related_resources"], "available_actions": task["required_actions"],
            "dependencies": task["dependencies"], "findings": self.missions.list_findings(mission["id"]),
            "decisions": self.missions.list_decisions(mission=mission["id"]),
            "blockers": self.missions.list_blockers(task=task["id"], unresolved_only=True),
            "evidence": self.missions.list_evidence(task["id"]),
        }

    # ---- Identity / Auth / Enrollment / Credential handler methods ----

    def auth_status(self) -> dict[str, Any]:
        return {"providers": sorted(self.auth.providers), "allow_local_fallback": self.auth.allow_local_fallback, "enrollment_mode": self.config.get("auth",{}).get("enrollment_mode","manual")}

    def auth_authenticate(self, method: str, credentials: dict[str, Any] | None = None) -> dict[str, Any]:
        try:
            context = self.auth.authenticate(method, credentials or {})
        except AuthenticationError as error:
            self.emit(Event("identity.authentication_failed","apx",{"method":method},{"error":str(error)}))
            raise ActionError(str(error)) from error
        self.emit(Event("identity.authenticated","apx",{"principal":context.principal_id},{"method":context.authentication_method,"issuer":context.issuer}))
        return context.to_dict()

    def identity_inspect(self, subject: str) -> dict[str, Any]:
        profile = self.actors.get(subject)
        if profile is None: raise ActionError(f"unknown identity {subject!r}")
        return profile.to_dict()

    def identity_list(self) -> dict[str, Any]:
        return {"identities": [p.to_dict() for p in self.actors.list()]}

    def identity_link(self, subject: str, openpower_subject: str, linked_by: str | None = None) -> dict[str, Any]:
        if self.actors.get(subject) is None: raise ActionError(f"unknown identity {subject!r}; declare it under [[actors]] first")
        self.identity_links.link(subject, openpower_subject, self.actors)
        return self.actors.get(subject).to_dict()

    def identity_unlink(self, subject: str, unlinked_by: str | None = None) -> dict[str, Any]:
        if self.actors.get(subject) is None: raise ActionError(f"unknown identity {subject!r}")
        self.identity_links.unlink(subject, self.actors)
        return self.actors.get(subject).to_dict()

    def identity_enrollment_request(self, machine_id: str, runtime: str, principal: str | None = None,
                                     requested_roles: list[str] | None = None, requested_scopes: list[str] | None = None,
                                     device_fingerprint: str | None = None) -> dict[str, Any]:
        mode = self.config.get("auth",{}).get("enrollment_mode","manual")
        try:
            record = self.enrollment.request(machine_id=machine_id, runtime=runtime, mode=mode, principal=principal,
                requested_roles=requested_roles, requested_scopes=requested_scopes, device_fingerprint=device_fingerprint)
        except EnrollmentError as error: raise ActionError(str(error)) from error
        self.emit(Event("identity.enrollment_requested","apx",{"request":record["id"]},{"machine_id":machine_id,"runtime":runtime,"mode":mode}))
        if record["status"]=="approved": self.emit(Event("identity.enrollment_approved","apx",{"request":record["id"]},{"resolved_by":record["resolved_by"]}))
        return record

    def identity_enrollment_status(self, request_id: str) -> dict[str, Any]:
        try: return self.enrollment.get(request_id)
        except EnrollmentError as error: raise ActionError(str(error)) from error

    def identity_enrollment_cancel(self, request_id: str, cancelled_by: str | None = None) -> dict[str, Any]:
        try: return self.enrollment.cancel(request_id, resolved_by=cancelled_by)
        except EnrollmentError as error: raise ActionError(str(error)) from error

    def identity_enrollment_approve(self, request_id: str, approved_by: str | None = None, openpower_ref: str | None = None) -> dict[str, Any]:
        try: record = self.enrollment.approve(request_id, resolved_by=approved_by, openpower_ref=openpower_ref)
        except EnrollmentError as error: raise ActionError(str(error)) from error
        self.emit(Event("identity.enrollment_approved","apx",{"request":request_id},{"resolved_by":approved_by}))
        return record

    def identity_enrollment_deny(self, request_id: str, denied_by: str | None = None) -> dict[str, Any]:
        try: record = self.enrollment.deny(request_id, resolved_by=denied_by)
        except EnrollmentError as error: raise ActionError(str(error)) from error
        self.emit(Event("identity.enrollment_denied","apx",{"request":request_id},{"resolved_by":denied_by}))
        return record

    def pairing_create(self, ttl_seconds: int = 600) -> dict[str, Any]:
        """One-time pairing code -- process-lifetime only by design (short-lived, not meant
        to survive a restart); prepares for future secure device pairing, not a full relay."""
        code = secrets.token_urlsafe(9)
        ttl = max(30, min(int(ttl_seconds), 3600))
        self._pairing_codes[code] = {"expires_at": time.time()+ttl, "status": "pending", "claimed_by": None}
        return {"code": code, "expires_in": ttl}

    def pairing_claim(self, code: str, claimant: str) -> dict[str, Any]:
        record = self._pairing_codes.get(code)
        if record is None: raise ActionError("unknown or already-consumed pairing code")
        if record["status"] != "pending": raise ActionError(f"pairing code already {record['status']}")
        if time.time() > record["expires_at"]:
            record["status"] = "expired"; raise ActionError("pairing code has expired")
        record["status"] = "claimed"; record["claimed_by"] = claimant
        return {"code": code, "status": "claimed", "claimed_by": claimant}

    def credential_issue(self, principal: str, **fields: Any) -> dict[str, Any]:
        try: record = self.actor_credentials.issue(principal, **fields)
        except ActorCredentialError as error: raise ActionError(str(error)) from error
        self.emit(Event("credential.created","apx",{"principal":principal,"credential":record["id"]},{"type":record["type"]}))
        return record

    def credential_inspect(self, credential_id: str) -> dict[str, Any]:
        try: return self.actor_credentials.inspect(credential_id)
        except ActorCredentialError as error: raise ActionError(str(error)) from error

    def credential_rotate(self, credential_id: str, fingerprint: str | None = None, secret_ref: str | None = None) -> dict[str, Any]:
        try: result = self.actor_credentials.rotate(credential_id, fingerprint=fingerprint, secret_ref=secret_ref)
        except ActorCredentialError as error: raise ActionError(str(error)) from error
        self.emit(Event("credential.rotated","apx",{"principal":result["current"]["principal"],"credential":result["current"]["id"]},{"replaces":credential_id}))
        return result

    def credential_confirm_rotation(self, previous_credential_id: str) -> dict[str, Any]:
        try: return self.actor_credentials.confirm_rotation(previous_credential_id)
        except ActorCredentialError as error: raise ActionError(str(error)) from error

    def credential_revoke(self, credential_id: str, revoked_by: str | None = None) -> dict[str, Any]:
        try: record = self.actor_credentials.revoke(credential_id)
        except ActorCredentialError as error: raise ActionError(str(error)) from error
        self.emit(Event("credential.revoked","apx",{"principal":record["principal"],"credential":credential_id},{"revoked_by":revoked_by}))
        return record

    def _emit_for_result(self, request: ActionRequest, result: ActionResult) -> None:
        if not result.ok and request.action.startswith("service."): event_name="service.failed"
        elif not result.ok and request.action in {"host.inspect","host.info","host.status"}: event_name="host.offline"
        elif request.action=="secret.rotate": event_name="credential.rotation_completed" if result.ok and isinstance(result.result,dict) and result.result.get("ok") else "credential.rotation_failed"
        else: event_name={
            "service.start":"service.started","service.stop":"service.stopped","service.restart":"service.restarted","file.copy":"file.copied","file.sync":"file.synced","host.shutdown":"host.shutdown_requested","secret.set":"secret.updated",
            "mission.create":"mission.created","mission.start":"mission.started","mission.complete":"mission.completed","mission.verify":"mission.verified" if result.ok and isinstance(result.result,dict) and (result.result.get("verification") or {}).get("verified") else "mission.completed","mission.block":"mission.blocked","mission.cancel":"mission.cancelled",
            "task.create":"task.created","task.claim":"task.claimed","task.start":"task.started","task.complete":"task.completed","task.verify":"task.verified" if result.ok and isinstance(result.result,dict) and (result.result.get("verification") or {}).get("verified") else "task.completed","task.block":"task.blocked","task.cancel":"task.cancelled",
            "finding.create":"finding.created","decision.record":"decision.recorded","blocker.create":"blocker.created","blocker.resolve":"blocker.resolved","evidence.attach":"evidence.attached",
            "identity.link":"identity.linked","identity.unlink":"identity.unlinked",
        }.get(request.action,"action.completed" if result.ok else "action.failed")
        try: duration_ms=max(0,int((datetime.now(timezone.utc)-datetime.fromisoformat(request.created_at.replace("Z","+00:00"))).total_seconds()*1000))
        except ValueError: duration_ms=None
        self.emit(Event(name=event_name,source="apx",subject=request.target,data={"action":request.action,"actor":request.actor,"provider":self.actions.get(request.action).provider if request.action in {a.name for a in self.actions.list()} else None,"status":result.status,"duration_ms":duration_ms,"receipt_id":result.receipt.receipt_id if result.receipt else None,"ok":result.ok,"error":result.error.to_dict() if result.error else None},correlation_id=request.request_id))

    def emit(self, event: Event) -> Event: return self.events.emit(event)

    def resources(self) -> list[Resource]:
        values=[Resource(id=f"host:{host.name}",kind="host",name=host.name,attributes={"transport":host.transport,"target":host.target,"connections":connection_list(host)["connections"]},groups=host.groups,tags=host.tags) for host in self.hosts.values()]
        values.extend(Resource(id=f"project:{project.name}",kind="project",name=project.name,attributes={"description":project.description,"services":project.services,"domains":project.domains},groups=project.groups,tags=project.tags) for project in self.projects.values())
        values.extend(Resource(id=f"mission:{m['id']}",kind="mission",name=m["title"],attributes={"project":m["project"],"status":m["status"],"objective":m["objective"]}) for m in self.missions.list_missions())
        values.extend(Resource(id=f"task:{t['id']}",kind="task",name=t["title"],attributes={"mission":t["mission"],"status":t["status"],"reason":t["reason"]}) for t in self.missions.list_tasks())
        for provider in self.providers.values(): values.extend(provider.manifest().resources)
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
