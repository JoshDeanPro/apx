from __future__ import annotations

from pathlib import Path
from typing import Any

from .cloud import LocalCloud
from .config import default_config_path
from .protocol import MCPServer


def diagnose(config: str | Path | None = None) -> dict[str,Any]:
    path=Path(config).expanduser() if config else default_config_path()
    report={"ok":True,"config":{"path":str(path),"ok":False},"hosts":[],"plugins":[],"mcp":{},"problems":[]}
    try:
        cloud=LocalCloud(path)
        report["config"]["ok"]=True
    except Exception as error:
        report["ok"]=False; report["config"]["error"]=str(error); report["problems"].append(str(error)); return report
    for host in cloud.hosts.values():
        item={"name":host.name,"transport":host.transport,"target":host.target,"reachable":False,"capabilities":[],"missing_optional":[]}
        try:
            info=cloud.core.host_info(host.name); item["reachable"]=True
            item["capabilities"]=sorted(name for name,value in info["capabilities"].items() if value["available"])
            for optional in ("git","rsync","scp"):
                if not info["capabilities"].get(optional,{}).get("available"): item["missing_optional"].append(optional)
        except Exception as error:
            item["error"]=str(error); report["ok"]=False; report["problems"].append(f"{host.name}: {error}")
        report["hosts"].append(item)
    report["plugins"]=cloud.plugin_manager.health
    for plugin in report["plugins"]:
        if not plugin["ok"]: report["ok"]=False; report["problems"].append(f"plugin {plugin['name']}: {plugin['error']}")
    try:
        tools=MCPServer(cloud).tools(); report["mcp"]={"available":True,"tools":len(tools)}
    except Exception as error:
        report["mcp"]={"available":False,"error":str(error)}; report["ok"]=False; report["problems"].append(f"MCP: {error}")
    if cloud.events.errors:
        report["ok"]=False; report["problems"].extend(f"event listener {e['owner']}: {e['error']}" for e in cloud.events.errors)
    return report

