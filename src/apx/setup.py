# SPDX-License-Identifier: MPL-2.0
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Callable

from .discovery import inspect_host
from .models import Host
from .files import atomic_write


def _quote(value: str) -> str: return json.dumps(value)


def initialize(path: str | Path, *, ssh_hosts: list[str] | None = None, interactive: bool = True, force: bool = False, input_fn: Callable[[str],str] = input) -> dict:
    destination=Path(path).expanduser()
    if destination.exists() and not force: raise FileExistsError(f"configuration already exists: {destination}; use --force to replace it")
    local=Host("local","local")
    discovered=inspect_host(local)
    # Name this machine after itself, not "local": the config is meant to be shared
    # across the fleet, where "local" would be a different computer on every node.
    local_name=re.sub(r"[^A-Za-z0-9_-]+","-",discovered["hostname"].split(".")[0]).strip("-").lower() or "local"
    local=Host(local_name,"local")
    configured=[]
    entries=list(ssh_hosts or [])
    if interactive and not entries:
        while True:
            answer=input_fn("Additional SSH host (name=target, blank to finish): ").strip()
            if not answer: break
            entries.append(answer)
    hosts=[local]
    errors=[]
    for entry in entries:
        if "=" not in entry:
            errors.append({"host":entry,"error":"expected name=target"}); continue
        name,target=entry.split("=",1)
        if not re.fullmatch(r"[A-Za-z][A-Za-z0-9_-]*",name) or not target.strip():
            errors.append({"host":entry,"error":"invalid host name or empty SSH target"}); continue
        host=Host(name,"ssh",target.strip())
        try:
            info=inspect_host(host); configured.append({"name":name,"target":target.strip(),"reachable":True,"hostname":info["hostname"]}); hosts.append(host)
        except Exception as error: errors.append({"host":name,"target":target.strip(),"error":str(error)})
    lines=["version = 1","","[node]",
           "# Which configured host this installation IS. The one machine-specific line",
           "# in this file; everything else can be shared with every other node.",
           f"name = {_quote(local_name)}",
           "","[[hosts]]",f"name = {_quote(local_name)}",'transport = "local"']
    for host in hosts[1:]: lines.extend(["","[[hosts]]",f"name = {_quote(host.name)}",'transport = "ssh"',f"target = {_quote(host.target or '')}"])
    atomic_write(destination,"\n".join(lines)+"\n")
    found=sorted(name for name,value in discovered["capabilities"].items() if value["available"])
    return {"config":str(destination),"local":{"hostname":discovered["hostname"],"os":discovered["os"],"architecture":discovered["architecture"],"capabilities":found},"ssh_hosts":configured,"errors":errors}
