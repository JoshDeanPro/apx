# SPDX-License-Identifier: MPL-2.0
from __future__ import annotations

from pathlib import Path
from typing import Any
import os
import shutil
import sys

from .cloud import APX
from .config import default_config_path
from .protocol import MCPServer
from .system import connection_status, scheduler_list, tailscale_status
from .foundation import inspect_foundation
from . import __version__


def diagnose(config: str | Path | None = None) -> dict[str,Any]:
    path=Path(config).expanduser() if config else default_config_path()
    foundation=inspect_foundation()
    invoked=Path(sys.argv[0]).resolve() if Path(sys.argv[0]).exists() else None
    inferred_method="managed-venv" if "openpower/runtimes" in str(Path(sys.prefix)) else "development_or_unknown"
    report={"ok":True,"status":"healthy","versions":{"apx":__version__},"runtime":{"python":sys.version.split()[0],"executable":sys.executable,"isolated":sys.prefix!=getattr(sys,"base_prefix",sys.prefix),"installation_method":os.environ.get("OPENPOWER_INSTALL_METHOD",inferred_method)},"path":{"apx":shutil.which("apx") or (str(invoked) if invoked else None)},"foundation":foundation,"config":{"path":str(path),"ok":False},"state_directory":str(path.parent),"hosts":[],"credentials":[],"connections":[],"plugins":[],"providers":[],"registry":{},"integrations":[],"databases":[],"mcp":{},"update":{"status":"unknown","note":"release metadata was not requested"},"problems":[],"fixes":[]}
    try:
        cloud=APX(path)
        report["config"]["ok"]=True
    except Exception as error:
        report["ok"]=False; report["status"]="misconfigured"; report["config"]["error"]=str(error); report["problems"].append(str(error)); report["fixes"].append(f"Create or repair {path} with `apx init --output {path}`."); return report
    report["registry"]={"status":"healthy","actions":len(cloud.actions.list())}
    report["providers"]=[provider.health().to_dict() for provider in cloud.providers.values()]
    for host in cloud.hosts.values():
        item={"name":host.name,"transport":host.transport,"target":host.target,"reachable":False,"capabilities":[],"missing_optional":[]}
        try:
            info=cloud.core.host_info(host.name); item["reachable"]=True
            item["capabilities"]=sorted(name for name,value in info["capabilities"].items() if value["available"])
            item["service_manager"]="systemd" if info["capabilities"]["systemd"]["available"] else "launchd" if info["capabilities"]["launchd"]["available"] else None
            jobs=scheduler_list(host); item["schedulers"]={name:sum(1 for job in jobs["jobs"] if job["scheduler"]==name) for name in jobs["schedulers"]}
            item["connections"]=connection_status(host)
            if info["capabilities"]["tailscale"]["available"]:
                tailscale=tailscale_status(host); item["tailscale"]={"installed":True,"connected":tailscale.get("connected",False),"identity":tailscale.get("identity"),"peer_count":len(tailscale.get("peers",[])),"configured_connection_matches":tailscale.get("configured_connection_matches",[])}
            else: item["tailscale"]={"installed":False,"connected":False,"peer_count":0}
            for optional in ("git","rsync","scp"):
                if not info["capabilities"].get(optional,{}).get("available"): item["missing_optional"].append(optional)
        except Exception as error:
            item["error"]=str(error); report["ok"]=False; report["problems"].append(f"{host.name}: {error}")
        report["hosts"].append(item)
    report["plugins"]=cloud.plugin_manager.health
    for name,metadata in sorted(cloud.plugin_manager.metadata.items()):
        health=next((item for item in report["plugins"] if item["name"]==name),{})
        report["integrations"].append({"name":name,"configured":health.get("configured",health.get("ok",False) and health.get("status")!="available_not_configured"),"status":health.get("status","ready" if health.get("ok") else "unhealthy"),"version":metadata.version_info.to_dict() if metadata.version_info else None,"actions":len(metadata.actions)})
    for value in cloud.config.get("databases",[]):
        report["databases"].append({key:value.get(key) for key in ("id","engine","host","port","provider","project","groups","tags") if value.get(key) is not None} | {"url_credential":value.get("url_credential"),"configured":True})
    report["connections"]=cloud.connection_health
    for connection in report["connections"]:
        if not connection["ok"]: report["ok"]=False; report["problems"].append(f"connection {connection['id']}: {connection['error']}")
    report["credentials"]=[]
    for credential_id in cloud.credentials.references:
        try:
            value=cloud.secrets.health(credential_id)
            report["credentials"].append({"id":credential_id,"available":bool(value.get("available")),"status":"healthy" if value.get("available") else "unavailable","source":value.get("source"),"lifecycle":value.get("lifecycle")})
        except Exception as error: report["credentials"].append({"id":credential_id,"available":False,"status":"misconfigured","error":str(error)})
    for credential in report["credentials"]:
        if not credential["available"]:
            report["ok"]=False
            report["problems"].append(f"credential {credential['id']}: configured but unavailable")
    for plugin in report["plugins"]:
        if not plugin["ok"]:
            report["ok"]=False
            reason=plugin.get("error") or f"missing credential references: {', '.join(plugin.get('missing_credentials',[]))}"
            report["problems"].append(f"plugin {plugin['name']}: {reason}")
    try:
        tools=MCPServer(cloud).tools(); report["mcp"]={"available":True,"tools":len(tools)}
    except Exception as error:
        report["mcp"]={"available":False,"error":str(error)}; report["ok"]=False; report["problems"].append(f"MCP: {error}")
    if cloud.events.errors:
        report["ok"]=False; report["problems"].extend(f"event listener {e['owner']}: {e['error']}" for e in cloud.events.errors)
    required_bad=[item for item in foundation["components"] if item["level"]=="foundation" and item["status"]!="healthy"]
    if required_bad:
        report["ok"]=False; report["status"]="misconfigured"
        report["problems"].extend(f"foundation {item['id']}: {item['detail']}" for item in required_bad)
    elif not report["ok"]: report["status"]="degraded"
    optional=[item["id"] for item in foundation["components"] if item["level"]=="optional" and item["status"]=="unavailable"]
    if optional: report["optional_missing"]=optional
    return report
