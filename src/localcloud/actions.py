from __future__ import annotations

import json
import os
import re
import subprocess
from dataclasses import dataclass
from typing import Any, Callable

from .discovery import inspect_host
from .axp import ActionDefinition
from .models import Host, Project
from .service_managers import manager_for
from .transports import transport_for


class ActionError(RuntimeError): pass


@dataclass(frozen=True)
class RegisteredAction:
    name: str
    description: str
    handler: Callable[..., Any]
    schema: dict[str, Any]
    read_only: bool = True
    destructive: bool = False

    def definition(self) -> ActionDefinition:
        return ActionDefinition(self.name,self.description,self.schema,self.read_only,self.destructive)


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


def _unit(value: str) -> str:
    if not re.fullmatch(r"[A-Za-z0-9_.@:-]+", value or ""):
        raise ActionError("invalid service name")
    return value


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
            if not r.ok: raise ActionError(r.stderr.strip() or f"launchd service {unit} was not found")
            return {"host":host,"service":unit,"manager":"launchd","status":r.stdout}
        r=transport_for(item).run(["systemctl","show",unit,"--no-pager","--property=Id,Description,LoadState,ActiveState,SubState,UnitFileState,MainPID"])
        if r.exit_code != 0: raise ActionError(r.stderr.strip() or f"service {unit} was not found")
        return {"host":host,"service":unit,"properties":dict(line.split("=",1) for line in r.stdout.splitlines() if "=" in line)}

    def service_control(self, verb: str, host: str, service: str) -> dict[str, Any]:
        item=self.host(host); unit=_unit(service)
        if not inspect_host(item)["capabilities"]["systemd"]["available"]:
            raise ActionError(f"service.{verb} currently requires systemd; {host} does not provide it")
        prefix=[] if item.transport != "local" else (["sudo","-n"] if hasattr(__import__('os'),'geteuid') and __import__('os').geteuid()!=0 else [])
        r=transport_for(item).run([*prefix,"systemctl",verb,unit],timeout=60)
        if not r.ok: raise ActionError(r.stderr.strip() or f"systemctl {verb} failed")
        return self.service_status(host,unit)

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
        src=self.host(source_host); dst=self.host(destination_host)
        def spec(host: Host,path: str) -> str: return path if host.transport=="local" else f"{host.target}:{path}"
        command=["scp","-3","-p",spec(src,source),spec(dst,destination)] if src.transport==dst.transport=="ssh" else ["scp","-p",spec(src,source),spec(dst,destination)]
        if src.transport==dst.transport=="local": command=["cp","-p",source,destination]
        r=subprocess.run(command,capture_output=True,text=True,timeout=120)
        if r.returncode: raise ActionError(r.stderr.strip() or "file copy failed")
        return {"source":{"host":source_host,"path":source},"destination":{"host":destination_host,"path":destination},"transport":"local" if command[0]=="cp" else "scp"}

    def file_sync(self, source_host: str, source: str, destination_host: str, destination: str, dry_run: bool = True) -> dict[str, Any]:
        src=self.host(source_host); dst=self.host(destination_host)
        for item in (src,dst):
            if not inspect_host(item)["capabilities"]["rsync"]["available"]: raise ActionError(f"files.sync requires rsync; rsync is not installed on host {item.name}")
        if src.transport==dst.transport=="ssh": raise ActionError("direct remote-to-remote rsync is not supported; use file.copy or sync through a local host")
        spec=lambda h,p: p if h.transport=="local" else f"{h.target}:{p}"
        command=["rsync","-a","--itemize-changes"] + (["--dry-run"] if dry_run else []) + [spec(src,source),spec(dst,destination)]
        r=subprocess.run(command,capture_output=True,text=True,timeout=300)
        if r.returncode: raise ActionError(r.stderr.strip() or "file sync failed")
        return {"dry_run":dry_run,"changes":r.stdout.splitlines()}

    def host_shutdown(self, host: str) -> dict[str, Any]:
        item=self.host(host); r=transport_for(item).run(["shutdown","-h","now"],timeout=10)
        if not r.ok: raise ActionError(r.stderr.strip() or "shutdown failed")
        return {"host":host,"requested":True}


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
    ]
    for spec in specs: r.register(RegisteredAction(*spec))
    r.alias("host.info","host.inspect")
    return r


Action = RegisteredAction
