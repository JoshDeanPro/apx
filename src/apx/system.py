# SPDX-License-Identifier: MIT
"""Read-only host technology, connectivity, service-manager, and scheduler discovery."""
from __future__ import annotations

import json
from typing import Any

from .actions import ActionError
from .discovery import inspect_host
from .models import Host
from .transports import transport_for, transports_for


import re


def connection_list(host: Host) -> dict[str,Any]:
    definitions=list(host.connections) or [{"adapter":host.transport,"target":host.target,"preferred":True}]
    return {"host":host.name,"connections":[{"id":value.get("id",f"{host.name}-{index+1}"),"adapter":value.get("adapter",value.get("transport","ssh")),"target":value.get("target"),"preferred":bool(value.get("preferred",index==0))} for index,value in enumerate(definitions)]}


def connection_status(host: Host) -> dict[str,Any]:
    values=[]
    definitions=connection_list(host)["connections"]
    for definition,transport in zip(definitions,transports_for(host)):
        try:
            result=transport.run(["true"],timeout=10)
            values.append({**definition,"usable":result.ok,"error":result.stderr.strip() or None})
        except Exception as error: values.append({**definition,"usable":False,"error":str(error)})
    selected=next((item["id"] for item in values if item["usable"]),None)
    return {"host":host.name,"selected":selected,"connections":values}


def tailscale_status(host: Host) -> dict[str,Any]:
    info=inspect_host(host)
    if not info["capabilities"]["tailscale"]["available"]:
        return {"host":host.name,"installed":False,"connected":False,"peers":[]}
    transport=transport_for(host)
    raw_command=str(info["capabilities"]["tailscale"].get("command") or "tailscale")
    command=raw_command if re.fullmatch(r"[/A-Za-z0-9_.-]+",raw_command) else "tailscale"
    version=transport.run([command,"version"],timeout=10)

    status=transport.run([command,"status","--json"],timeout=15)
    if not status.ok:
        return {"host":host.name,"installed":True,"connected":False,"version":version.stdout.splitlines()[0] if version.ok else None,"error":status.stderr.strip() or "status unavailable","peers":[]}
    data=json.loads(status.stdout)
    peers=[]
    for peer in data.get("Peer",{}).values():
        capabilities=peer.get("Capabilities",{})
        ssh_capability="https://tailscale.com/cap/ssh" in capabilities
        peers.append({"id":peer.get("ID"),"hostname":peer.get("HostName"),"dns_name":peer.get("DNSName"),"addresses":peer.get("TailscaleIPs",[]),"online":peer.get("Online"),"ssh":ssh_capability})
    self_info=data.get("Self",{})
    targets={value.get("target") for value in host.connections if value.get("target")}
    matched=[peer["hostname"] for peer in peers if targets.intersection({peer.get("hostname"),peer.get("dns_name"),*peer.get("addresses",[])})]
    return {"host":host.name,"installed":True,"connected":data.get("BackendState")=="Running","backend_state":data.get("BackendState"),"version":version.stdout.splitlines()[0] if version.ok else None,"identity":{"hostname":self_info.get("HostName"),"dns_name":self_info.get("DNSName"),"addresses":self_info.get("TailscaleIPs",[])},"peers":peers,"configured_connection_matches":matched}


def scheduler_list(host: Host) -> dict[str,Any]:
    info=inspect_host(host); transport=transport_for(host); jobs=[]
    if info["capabilities"]["cron"]["available"]:
        try:
            result=transport.run(["crontab","-l"],timeout=15)
            if result.ok:
                for index,line in enumerate(result.stdout.splitlines(),1):
                    stripped=line.strip()
                    if stripped and not stripped.startswith("#"):
                        parts=stripped.split(None,5)
                        if len(parts)>=6: jobs.append({"id":f"cron:{host.name}:{index}","name":f"user-cron-{index}","host":host.name,"scheduler":"cron","schedule":" ".join(parts[:5]),"command":parts[5],"enabled":True})
        except Exception: pass
    if info["capabilities"]["systemd"]["available"]:
        try:
            result=transport.run(["systemctl","list-timers","--all","--no-pager","--no-legend"],timeout=20)
            if result.ok:
                for index,line in enumerate(result.stdout.splitlines(),1):
                    parts=line.split()
                    if len(parts)>=2:
                        unit=next((part for part in reversed(parts) if part.endswith(".timer")),None)
                        if unit: jobs.append({"id":f"systemd_timer:{host.name}:{unit}","name":unit,"host":host.name,"scheduler":"systemd_timer","schedule":" ".join(parts[:5]),"service":unit.removesuffix(".timer")+".service","enabled":True})
        except Exception: pass
    if info["capabilities"]["launchd"]["available"]:
        try:
            script='''import glob,json,os,plistlib\nout=[]\npaths=["/Library/LaunchAgents/*.plist","/Library/LaunchDaemons/*.plist",os.path.expanduser("~/Library/LaunchAgents/*.plist")]\nfor pattern in paths:\n for path in glob.glob(pattern):\n  try:\n   with open(path,"rb") as stream: item=plistlib.load(stream)\n   schedule=item.get("StartCalendarInterval") or item.get("StartInterval")\n   if schedule is not None: out.append({"name":item.get("Label",os.path.basename(path)),"schedule":schedule,"path":path,"enabled":not item.get("Disabled",False)})\n  except Exception: pass\nprint(json.dumps(out))'''
            result=transport.run(["python3","-c",script],timeout=20)
            if result.ok:
                for item in json.loads(result.stdout): jobs.append({"id":f"launchd:{host.name}:{item['name']}","host":host.name,"scheduler":"launchd",**item})
        except Exception: pass
    return {"host":host.name,"jobs":jobs,"schedulers":sorted({job["scheduler"] for job in jobs})}



def scheduler_inspect(host: Host, job: str) -> dict[str,Any]:
    for item in scheduler_list(host)["jobs"]:
        if item["id"]==job or item["name"]==job: return item
    raise ActionError(f"scheduler job {job!r} was not found on {host.name}")
