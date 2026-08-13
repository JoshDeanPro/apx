# SPDX-License-Identifier: MPL-2.0
"""Conservative local software discovery: inspect existing capabilities, install none."""
from __future__ import annotations

from pathlib import Path
import platform
import shutil

from .axp import Capability, Resource


KNOWN={"git":"project.version_control","ssh":"transport.ssh","rg":"search.fast","rsync":"file.sync.optimized","code":"editor.code","open":"application.open"}


def discover_local_software(*,application_limit: int=200) -> tuple[tuple[Resource,...],tuple[Capability,...]]:
    resources=[]; capabilities=[]
    for command,capability in KNOWN.items():
        path=shutil.which(command)
        if not path: continue
        resource=Resource(f"software:{command}","application",command,{"executable":path},tags=("local","discovered"))
        resources.append(resource); capabilities.append(Capability(capability,resource.id,f"Capability provided by installed {command}",provenance="local_native",source="software.discovery"))
    if platform.system()=="Darwin":
        count=0
        for root in (Path("/Applications"),Path.home()/"Applications"):
            if not root.is_dir(): continue
            for path in sorted(root.glob("*.app")):
                if count>=application_limit: break
                name=path.stem; resource=Resource(f"application:{name.lower().replace(' ','-')}","application",name,{"path":str(path)},tags=("local","macos"))
                resources.append(resource); capabilities.append(Capability("application.open",resource.id,"Open installed application",actions=("application.open",),provenance="local_native",source="software.discovery")); count+=1
    return tuple(resources),tuple(capabilities)
