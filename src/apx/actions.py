# SPDX-License-Identifier: MIT
from __future__ import annotations

import json
import os
import re
import time
from dataclasses import dataclass
from typing import Any, Callable

from jsonschema.validators import Draft202012Validator

from .discovery import inspect_host
from .axp import ActionDefinition
from .models import Host, Project
from .service_managers import manager_for
from .transports import transport_for
from .process import ProcessError,ProcessTimeout,run


class ActionError(RuntimeError): pass


@dataclass(frozen=True)
class RegisteredAction:
    name: str
    description: str
    handler: Callable[..., Any]
    schema: dict[str, Any]
    read_only: bool = True
    destructive: bool = False
    available: bool = True
    # --- Action Providers metadata -- all optional, all backward compatible ---------
    # `confirmation` defaults to "none" (not inferred from `destructive`) deliberately:
    # existing destructive actions are already gated by the CLI's --yes / MCP's
    # confirm=true, a mechanism that predates and is unrelated to this one. Making
    # `confirmation` default to anything but "none" here would retroactively require
    # every existing destructive action to start carrying a request.confirmation
    # payload nothing currently sends, breaking them. New provider actions that want
    # the new gate (see cloud.execute) opt in by setting `confirmation` explicitly.
    output_schema: dict[str, Any] | None = None
    risk: str | None = None  # None = infer from read_only/destructive, see _risk()
    confirmation: str = "none"
    reversible: bool = False
    reverse_action: str | None = None
    idempotent: bool | None = None  # None = infer from read_only, see _idempotent()
    required_permissions: tuple[str, ...] = ()
    provider: str | None = None
    provenance: str = "native_provider"
    tags: tuple[str, ...] = ()
    version: str = "1.0"
    deprecated: bool = False
    resource_type: str | None = None
    side_effects: tuple[str, ...] = ()
    credential_requirements: tuple[str, ...] = ()
    actor_requirements: tuple[str, ...] = ()
    expected_verification: str | None = None
    remediation_action: str | None = None
    prepare_handler: Callable[..., Any] | None = None
    verify_handler: Callable[..., Any] | None = None
    retry: str | None = None
    preconditions: tuple[dict[str, Any], ...] = ()
    postconditions: tuple[dict[str, Any], ...] = ()
    constraints: dict[str, Any] = None  # type: ignore[assignment]
    reversal_window: int | None = None
    deterministic: bool = True
    supports_dry_run: bool = False

    def __post_init__(self):
        if not re.fullmatch(r"^[a-zA-Z0-9_.-]+$", self.name): raise ValueError(f"invalid action identifier: {self.name}")
        from .axp import CONFIRMATION_LEVELS
        if self.confirmation not in CONFIRMATION_LEVELS: raise ValueError(f"invalid confirmation: {self.confirmation}")
        for actor in self.actor_requirements:
            if ":" not in actor and actor not in {"human", "agent", "system", "anonymous"}:
                raise ValueError(f"unsupported actor requirement format: {actor}")
        Draft202012Validator.check_schema(self.schema)
        if self.output_schema is not None:
            Draft202012Validator.check_schema(self.output_schema)

    def _risk(self) -> str:
        if self.risk is not None: return self.risk
        if self.destructive: return "destructive"
        if not self.read_only: return "account_change"
        return "read"

    def _idempotent(self) -> bool:
        return self.read_only if self.idempotent is None else self.idempotent

    def definition(self) -> ActionDefinition:
        from .axp import ActionRequirements
        reqs = ActionRequirements(
            permissions=self.required_permissions,
            credentials=self.credential_requirements,
            actor_types=self.actor_requirements,
            preconditions=self.preconditions,
            approval_level=self.confirmation
        )
        return ActionDefinition(
            self.name,self.description,self.schema,self.available,self.read_only,self.destructive,
            output_schema=self.output_schema,risk=self._risk(),confirmation=self.confirmation,
            reversible=self.reversible,reverse_action=self.reverse_action,idempotent=self._idempotent(),
            requirements=reqs,provider=self.provider,provenance=self.provenance,
            tags=self.tags,version=self.version,deprecated=self.deprecated,
            resource_type=self.resource_type,side_effects=self.side_effects,
            expected_verification=self.expected_verification,remediation_action=self.remediation_action,
            retry=self.retry,postconditions=self.postconditions,
            constraints=self.constraints or {},reversal_window=self.reversal_window,
            extensions={"execution":{"deterministic":self.deterministic,"supports_dry_run":self.supports_dry_run}},
        )


class ActionRegistry:
    def __init__(self): self._actions: dict[str, RegisteredAction] = {}; self._aliases: dict[str,str] = {}
    def register(self, action: RegisteredAction) -> None:
        if action.name in self._actions: raise ValueError(f"duplicate action {action.name}")
        self._actions[action.name] = action
    def get(self, name: str) -> RegisteredAction:
        name=self._aliases.get(name,name)
        if name not in self._actions: raise ActionError(f"unknown action {name!r}")
        return self._actions[name]
    def list(self) -> list[RegisteredAction]: return list(self._actions.values())
    def alias(self, old: str, canonical: str) -> None:
        if canonical not in self._actions: raise ValueError(f"unknown canonical action {canonical}")
        self._aliases[old]=canonical
    def describe(self, *, namespaces: tuple[str,...]=(), predicate: Callable[[RegisteredAction],bool]|None=None, compact: bool=True) -> list[dict[str,Any]]:
        values=[]
        for action in self.list():
            if namespaces and not any(action.name==item or action.name.startswith(item+".") for item in namespaces): continue
            if predicate and not predicate(action): continue
            definition=action.definition()
            if compact:
                values.append({"id":definition.id,"description":definition.description,"args":list(definition.input_schema.get("properties",{})),"required":list(definition.input_schema.get("required",())),"permission":list(definition.requirements.permissions) or [definition.id],"risk":definition.risk,"confirmation":definition.confirmation,"idempotent":definition.idempotent,"deterministic":action.deterministic})
            else: values.append(definition.to_dict())
        return values


def _unit(value: str) -> str:
    if not re.fullmatch(r"[A-Za-z0-9_.@:-]+", value or ""):
        raise ActionError("invalid service name")
    return value


# Read-only ad hoc diagnostics only -- every entry is either unconditionally safe
# (a bare status/inspect command with no destructive subcommand) or restricted to
# an explicit subcommand allowlist. Value None means any args are accepted because
# the command itself has no mutating mode. None of these commands can write,
# delete, or execute arbitrary further commands. Extend deliberately, not by habit.
EXEC_ALLOWLIST: dict[str, tuple[str, ...] | None] = {
    "systemctl": ("status", "is-active", "is-enabled", "list-units", "list-timers"),
    "journalctl": None,
    "docker": ("ps", "logs", "stats", "inspect", "images"),
    "podman": ("ps", "logs", "stats", "inspect", "images"),
    "df": None, "du": None, "free": None, "uptime": None, "uname": None,
    "ps": None, "top": None, "vmstat": None,
    "ls": None, "cat": None, "head": None, "tail": None,
    "git": ("status", "log", "diff", "branch", "show", "rev-parse"),
    "ping": None, "dig": None, "nslookup": None, "ss": None, "netstat": None,
    "caddy": ("version", "validate"),
}

# EXEC_ALLOWLIST only vets `args[0]` (the subcommand); everything after that was
# passed straight to the process, so an allowlisted read-only subcommand could
# still carry a destructive flag (`git branch -D main`, `journalctl
# --vacuum-time=1s`) -- exactly the "cannot write, delete, or execute arbitrary
# further commands" guarantee this allowlist exists to make. Checked against
# EVERY argument (not just args[0]), for every command, regardless of whether
# that command has a subcommand allowlist above.
EXEC_DENIED_FLAG_PREFIXES: dict[str, tuple[str, ...]] = {
    "journalctl": ("--vacuum", "--rotate", "--flush", "--sync", "--relinquish-var"),
    "git": ("-D", "-d", "-M", "-m", "-f", "--delete", "--force", "--move"),
}


class CoreActions:
    def __init__(self, hosts: dict[str, Host], projects: dict[str, Project]):
        self.hosts, self.projects = hosts, projects

    def host(self, name: str) -> Host:
        try: return self.hosts[name]
        except KeyError as error: raise ActionError(f"unknown host {name!r}; known: {', '.join(self.hosts)}") from error

    def host_list(self) -> dict[str, Any]: return {"hosts": [host.to_dict() for host in self.hosts.values()]}
    def host_info(self, host: str) -> dict[str, Any]: return inspect_host(self.host(host))
    def host_status(self, host: str) -> dict[str, Any]:
        item = self.host(host); t = transport_for(item)
        info = inspect_host(item)
        command = ["systemctl", "list-units", "--state=failed", "--no-pager", "--no-legend"] if info["capabilities"]["systemd"]["available"] else ["uptime"]
        result = t.run(command, timeout=20)
        return {"host": host, "reachable": True, "uptime": t.run(["uptime"]).stdout.strip(), "failed_services": result.stdout.splitlines() if command[0] == "systemctl" else [], "disk": info["disk"]}

    def service_list(self, host: str) -> dict[str, Any]:
        item = self.host(host); info = inspect_host(item)
        if not info["capabilities"]["systemd"]["available"]:
            if info["capabilities"]["launchd"]["available"]:
                result=transport_for(item).run(["launchctl","list"])
                services=[]
                for line in result.stdout.splitlines()[1:]:
                    parts=line.split(None,2)
                    if len(parts)==3: services.append({"name":parts[2],"pid":None if parts[0]=="-" else parts[0],"last_exit_status":parts[1]})
                manager=manager_for(info)
                return {"host":host,"manager":"launchd","manager_capabilities":manager.__dict__ if manager else None,"services":services}
            return {"host":host,"manager":None,"services":[],"note":"no supported service manager was discovered"}
        r = transport_for(item).run(["systemctl", "list-units", "--type=service", "--all", "--no-pager", "--no-legend"], timeout=30)
        services=[]
        for line in r.stdout.splitlines():
            parts=line.replace("●", " ").split(None,4)
            if len(parts)>=4: services.append({"name":parts[0],"load":parts[1],"active":parts[2],"state":parts[3],"description":parts[4] if len(parts)>4 else ""})
        manager=manager_for(info)
        return {"host":host,"manager":"systemd","manager_capabilities":manager.__dict__ if manager else None,"services":services}

    def service_status(self, host: str, service: str) -> dict[str, Any]:
        item=self.host(host); unit=_unit(service)
        info=inspect_host(item)
        if not info["capabilities"]["systemd"]["available"]:
            if not info["capabilities"]["launchd"]["available"]: raise ActionError(f"no supported service manager on {host}")
            r=transport_for(item).run(["launchctl","print",f"gui/{os.getuid()}/{unit}"])
            if not r.ok:
                # launchctl's own text for "genuinely not loaded" vs. every other way this
                # probe can fail (permission error, transient launchd hiccup, ...) -- only
                # the former is safe to report as state=inactive. Collapsing both (as this
                # used to) let service.stop's pre-check see a broken probe as "already
                # stopped" and skip the real `launchctl bootout`, silently no-op'ing a stop.
                stderr=(r.stderr or "").lower()
                if "could not find service" in stderr or "no such process" in stderr:
                    return {"host":host,"service":unit,"manager":"launchd","state":"inactive","summary":f"{unit} is not loaded"}
                raise ActionError(r.stderr.strip() or f"launchctl print failed for {unit} (exit {r.exit_code})")
            raw_state=next((line.split("=",1)[1].strip() for line in r.stdout.splitlines() if line.strip().startswith("state =")),"unknown")
            normalized=raw_state.lower()
            # "running"/"not running" are the only two confirmed-exact launchctl strings;
            # a loaded-but-idle on-demand/socket-activated job (its normal steady state,
            # not a fault) reports something else entirely, e.g. "waiting" -- previously
            # any such string fell through to "unknown", which post-control verification
            # treats as neither active nor inactive and fails even a correct start/stop.
            if normalized=="not running": state="inactive"
            elif "running" in normalized: state="active"
            elif "waiting" in normalized or "scheduled" in normalized: state="active"
            else: state="unknown"
            return {"host":host,"service":unit,"manager":"launchd","state":state,"substate":raw_state,"summary":f"{unit} is {raw_state}","raw_output":r.stdout}
        r=transport_for(item).run(["systemctl","show",unit,"--no-pager","--property=Id,Description,LoadState,ActiveState,SubState,UnitFileState,MainPID"])
        if r.exit_code != 0: raise ActionError(r.stderr.strip() or f"service {unit} was not found")
        properties=dict(line.split("=",1) for line in r.stdout.splitlines() if "=" in line)
        return {"host":host,"service":unit,"manager":"systemd","state":properties.get("ActiveState","unknown"),"substate":properties.get("SubState"),"summary":f"{unit} is {properties.get('ActiveState','unknown')}","properties":properties}

    def service_control(self, verb: str, host: str, service: str) -> dict[str, Any]:
        item=self.host(host); unit=_unit(service); info=inspect_host(item)
        if info["capabilities"]["systemd"]["available"]: return self._service_control_systemd(verb,host,item,unit)
        if info["capabilities"]["launchd"]["available"]: return self._service_control_launchd(verb,host,item,unit)
        raise ActionError(f"service.{verb} requires systemd or launchd; {host} provides neither")

    # Verification retries a few times with a short linear backoff before declaring a
    # control command failed: `systemctl`/`launchctl` return as soon as the start/stop
    # *job* completes, not once the unit has actually settled into its new state (a
    # Type=notify unit, or one with slow shutdown hooks, can still read as
    # "activating"/mid-transition on the very next probe despite genuinely succeeding).
    # A transient probe failure (bug: launchd probes can themselves error) is retried
    # too rather than treated as a verification failure.
    _VERIFY_RETRIES=4
    _VERIFY_DELAY_SECONDS=0.5

    def _verify_service_state(self, host: str, unit: str, expected: str) -> dict[str, Any]:
        last_state: dict[str, Any] | None = None; last_error: ActionError | None = None
        for attempt in range(self._VERIFY_RETRIES):
            if attempt: time.sleep(self._VERIFY_DELAY_SECONDS*attempt)
            try: last_state=self.service_status(host,unit)
            except ActionError as error: last_error=error; continue
            if last_state.get("state")==expected: return last_state
        if last_state is not None: return last_state
        raise last_error  # every attempt failed to even read status

    def _service_control_systemd(self, verb: str, host: str, item: Host, unit: str) -> dict[str, Any]:
        before=self.service_status(host,unit); started=time.monotonic()
        if verb in {"start","stop"} and ((verb=="start" and before.get("state")=="active") or (verb=="stop" and before.get("state")=="inactive")):
            return {"host":host,"service":unit,"manager":"systemd","state":before["state"],"changed":False,"before":before["state"],"after":before["state"],"verified":True,"duration_ms":round((time.monotonic()-started)*1000,3),"summary":f"{unit} was already {before['state']}"}
        prefix=[] if item.transport != "local" else (["sudo","-n"] if hasattr(__import__('os'),'geteuid') and __import__('os').geteuid()!=0 else [])
        r=transport_for(item).run([*prefix,"systemctl",verb,unit],timeout=60)
        if not r.ok: raise ActionError(r.stderr.strip() or f"systemctl {verb} failed")
        expected="inactive" if verb=="stop" else "active"
        after=self._verify_service_state(host,unit,expected)
        if after.get("state")!=expected: raise ActionError(f"service {unit} {verb} completed but verification found state {after.get('state')}")
        return {"host":host,"service":unit,"manager":"systemd","state":after["state"],"substate":after.get("substate"),"changed":True,"before":before.get("state"),"after":after["state"],"verified":True,"duration_ms":round((time.monotonic()-started)*1000,3),"summary":f"{unit} is {after['state']}"}

    def _service_control_launchd(self, verb: str, host: str, item: Host, unit: str) -> dict[str, Any]:
        before=self.service_status(host,unit); started=time.monotonic()
        if verb in {"start","stop"} and ((verb=="start" and before.get("state")=="active") or (verb=="stop" and before.get("state")=="inactive")):
            return {"host":host,"service":unit,"manager":"launchd","state":before["state"],"changed":False,"before":before["state"],"after":before["state"],"verified":True,"duration_ms":round((time.monotonic()-started)*1000,3),"summary":f"{unit} was already {before['state']}"}
        domain=f"gui/{os.getuid()}/{unit}"
        # bootout fully unloads (a clean stop); kickstart starts if not running,
        # -k forces a fresh instance for restart. No shell metacharacter surface --
        # argv-only, same guarantee CoreActions gives every other transport.run() call.
        argv={"start":["launchctl","kickstart",domain],"stop":["launchctl","bootout",domain],"restart":["launchctl","kickstart","-k",domain]}[verb]
        r=transport_for(item).run(argv,timeout=30)
        if not r.ok: raise ActionError(r.stderr.strip() or f"launchctl {verb} failed")
        expected="inactive" if verb=="stop" else "active"
        after=self._verify_service_state(host,unit,expected)
        if after.get("state")!=expected: raise ActionError(f"service {unit} {verb} completed but verification found state {after.get('state')}")
        return {"host":host,"service":unit,"manager":"launchd","state":after["state"],"substate":after.get("substate"),"changed":True,"before":before.get("state"),"after":after["state"],"verified":True,"duration_ms":round((time.monotonic()-started)*1000,3),"summary":f"{unit} is {after['state']}"}

    def logs_read(self, host: str, service: str | None = None, lines: int = 100) -> dict[str, Any]:
        item=self.host(host); info=inspect_host(item)
        if not info["capabilities"]["systemd"]["available"]:
            if info["os"]=="Darwin":
                argv=["log","show","--style","compact","--last","1h"]
                if service: argv.extend(["--predicate",f'process == "{_unit(service)}"'])
                r=transport_for(item).run(argv,timeout=30)
                if not r.ok: raise ActionError(r.stderr.strip() or "could not read unified logs")
                return {"host":host,"service":service,"lines":r.stdout.splitlines()[-max(1,min(lines,2000)):]}
            raise ActionError(f"logs.read requires journald or macOS unified logging; neither was discovered on {host}")
        argv=["journalctl","--no-pager","-n",str(max(1,min(lines,2000)))]
        if service: argv.extend(["-u",_unit(service)])
        r=transport_for(item).run(argv,timeout=30)
        if not r.ok: raise ActionError(r.stderr.strip() or "could not read logs")
        return {"host":host,"service":service,"lines":r.stdout.splitlines()}

    def project_list(self) -> dict[str, Any]: return {"projects":[p.to_dict() for p in self.projects.values()]}
    def project_inspect(self, project: str) -> dict[str, Any]:
        if project not in self.projects: raise ActionError(f"unknown project {project!r}")
        p=self.projects[project]; locations=[]
        for loc in p.locations:
            transport=transport_for(self.host(loc.host))
            exists=transport.run(["test","-e",loc.path],timeout=20).exit_code==0
            bare=transport.run(["git","-C",loc.path,"rev-parse","--is-bare-repository"],timeout=20) if exists else None
            r=transport.run(["git","-C",loc.path,"status","--short","--branch"],timeout=20) if exists and (bare is None or bare.stdout.strip()!="true") else None
            locations.append({"host":loc.host,"path":loc.path,"role":loc.role,"exists":exists,"bare_repository":bool(bare and bare.stdout.strip()=="true"),"git_status":r.stdout.strip() if r and r.exit_code==0 else None})
        return {**p.to_dict(),"locations":locations}

    def project_discover(self, host: str, roots: list[str] | None = None) -> dict[str, Any]:
        roots=roots or (["/Users"] if self.host(host).transport=="local" else ["/srv","/opt","/root/Projects","/home"])
        script='''import json,os,sys\nroots=json.loads(sys.argv[1]); out=[]\nfor root in roots:\n if not os.path.isdir(root): continue\n for base,dirs,files in os.walk(root):\n  depth=base[len(root):].count(os.sep)\n  dirs[:]=[d for d in dirs if d not in {"node_modules",".venv","venv","Library",".cache",".Trash",".next","dist","build"}]\n  if ".git" in dirs:\n   out.append({"path":base,"kind":"git"}); dirs.remove(".git")\n  elif any(f in files for f in ("pyproject.toml","package.json","Cargo.toml","go.mod")):\n   out.append({"path":base,"kind":"project"})\n  if depth>=4: dirs[:]=[]\nprint(json.dumps(out[:1000]))'''
        r=transport_for(self.host(host)).run(["python3","-c",script,json.dumps(roots)],timeout=60)
        if not r.ok: raise ActionError(r.stderr.strip() or "project discovery failed")
        return {"host":host,"projects":json.loads(r.stdout)}

    def file_copy(self, source_host: str, source: str, destination_host: str, destination: str) -> dict[str, Any]:
        if source.startswith("-") or destination.startswith("-"): raise ActionError("file paths must not start with '-'")
        if "\x00" in source or "\x00" in destination: raise ActionError("invalid character in file path")
        src=self.host(source_host); dst=self.host(destination_host)
        def spec(host: Host,path: str) -> str: return path if host.transport=="local" else f"{host.target}:{path}"
        command=["scp","-3","-p",spec(src,source),spec(dst,destination)] if src.transport==dst.transport=="ssh" else ["scp","-p",spec(src,source),spec(dst,destination)]
        if src.transport==dst.transport=="local": command=["cp","-p",source,destination]
        try: r=run(command,timeout=120)
        except (ProcessError,ProcessTimeout) as error: raise ActionError(str(error)) from error
        if not r.ok: raise ActionError(r.stderr.strip() or "file copy failed")
        return {"source":{"host":source_host,"path":source},"destination":{"host":destination_host,"path":destination},"transport":"local" if command[0]=="cp" else "scp"}

    def file_sync(self, source_host: str, source: str, destination_host: str, destination: str, dry_run: bool = True) -> dict[str, Any]:
        if source.startswith("-") or destination.startswith("-"): raise ActionError("file paths must not start with '-'")
        if "\x00" in source or "\x00" in destination: raise ActionError("invalid character in file path")
        src=self.host(source_host); dst=self.host(destination_host)
        for item in (src,dst):
            if not inspect_host(item)["capabilities"]["rsync"]["available"]: raise ActionError(f"files.sync requires rsync; rsync is not installed on host {item.name}")
        if src.transport==dst.transport=="ssh": raise ActionError("direct remote-to-remote rsync is not supported; use file.copy or sync through a local host")
        spec=lambda h,p: p if h.transport=="local" else f"{h.target}:{p}"
        command=["rsync","-a","--itemize-changes"] + (["--dry-run"] if dry_run else []) + [spec(src,source),spec(dst,destination)]
        try: r=run(command,timeout=300)
        except (ProcessError,ProcessTimeout) as error: raise ActionError(str(error)) from error
        if not r.ok: raise ActionError(r.stderr.strip() or "file sync failed")
        return {"dry_run":dry_run,"changes":r.stdout.splitlines()}


    def host_shutdown(self, host: str) -> dict[str, Any]:
        item=self.host(host); r=transport_for(item).run(["shutdown","-h","now"],timeout=10)
        if not r.ok: raise ActionError(r.stderr.strip() or "shutdown failed")
        return {"host":host,"requested":True}

    def exec_diagnostic(self, host: str, command: str, args: list[str] | None = None) -> dict[str, Any]:
        item=self.host(host); args=list(args or [])
        if command not in EXEC_ALLOWLIST:
            raise ActionError(f"{command!r} is not in the diagnostic exec allowlist: {', '.join(sorted(EXEC_ALLOWLIST))}")
        allowed_subcommands=EXEC_ALLOWLIST[command]
        if allowed_subcommands is not None and (not args or args[0] not in allowed_subcommands):
            raise ActionError(f"{command} requires its first argument to be one of: {', '.join(allowed_subcommands)}")
        denied_prefixes=EXEC_DENIED_FLAG_PREFIXES.get(command,())
        offending=[arg for arg in args if any(arg.startswith(prefix) for prefix in denied_prefixes)]
        if offending:
            raise ActionError(f"{command} does not permit {', '.join(sorted(set(offending)))} through the diagnostic exec allowlist")
        r=transport_for(item).run([command,*args],timeout=20)
        return {"host":host,"command":command,"args":args,"exit_code":r.exit_code,"ok":r.ok,"stdout":r.stdout[:12000],"stderr":r.stderr[:2000]}


def build_registry(core: CoreActions) -> ActionRegistry:
    r=ActionRegistry(); obj=lambda props,required=[]:{"type":"object","properties":props,"required":required,"additionalProperties":False}; s={"type":"string"}
    specs=[
      ("host.list","List configured hosts",core.host_list,obj({}),True,False),
      ("host.inspect","Discover host identity and capabilities",core.host_info,obj({"host":s},["host"]),True,False),
      ("host.status","Read host status",core.host_status,obj({"host":s},["host"]),True,False),
      ("service.list","List services",core.service_list,obj({"host":s},["host"]),True,False),
      ("service.status","Read service status",core.service_status,obj({"host":s,"service":s},["host","service"]),True,False),
      ("service.inspect","Inspect service-manager state",core.service_status,obj({"host":s,"service":s},["host","service"]),True,False),
      ("service.start","Start a service",lambda **k:core.service_control("start",**k),obj({"host":s,"service":s},["host","service"]),False,False),
      ("service.stop","Stop a service",lambda **k:core.service_control("stop",**k),obj({"host":s,"service":s},["host","service"]),False,True),
      ("service.restart","Restart a service",lambda **k:core.service_control("restart",**k),obj({"host":s,"service":s},["host","service"]),False,True),
      ("logs.read","Read system journal",core.logs_read,obj({"host":s,"service":s,"lines":{"type":"integer","minimum":1,"maximum":2000}},["host"]),True,False),
      ("file.copy","Copy a file between hosts",core.file_copy,obj({"source_host":s,"source":s,"destination_host":s,"destination":s},["source_host","source","destination_host","destination"]),False,False),
      ("file.sync","Synchronize files with rsync",core.file_sync,obj({"source_host":s,"source":s,"destination_host":s,"destination":s,"dry_run":{"type":"boolean"}},["source_host","source","destination_host","destination"]),False,False),
      ("project.list","List configured projects",core.project_list,obj({}),True,False),
      ("project.inspect","Inspect a related project",core.project_inspect,obj({"project":s},["project"]),True,False),
      ("project.discover","Discover repositories and project manifests",core.project_discover,obj({"host":s,"roots":{"type":"array","items":s}},["host"]),True,False),
      ("host.shutdown","Shut down a host",core.host_shutdown,obj({"host":s},["host"]),False,True),
      ("host.exec","Run an allowlisted read-only diagnostic command on a host (see actions.EXEC_ALLOWLIST) -- argv-only, no shell parsing, no destructive commands",core.exec_diagnostic,obj({"host":s,"command":s,"args":{"type":"array","items":s}},["host","command"]),True,False),
    ]
    for spec in specs:
        action=RegisteredAction(*spec)
        if action.name.startswith("service."):
            action=RegisteredAction(*spec,output_schema={"type":"object"},risk="read" if action.read_only else "account_change",confirmation="none" if action.read_only else "confirm",idempotent=action.name in {"service.status","service.inspect","service.list","service.start","service.stop"},required_permissions=("service.read" if action.read_only else action.name,),resource_type="service",expected_verification="service state matches requested transition" if not action.read_only else None,retry="safe" if action.read_only else "idempotency_required" if action.name in {"service.start","service.stop"} else "never")
        elif action.name=="file.sync": action=RegisteredAction(*spec,supports_dry_run=True,idempotent=True,risk="low_change")
        r.register(action)
    r.alias("host.info","host.inspect")
    return r


Action = RegisteredAction
