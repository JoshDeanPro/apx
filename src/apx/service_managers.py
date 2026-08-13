# SPDX-License-Identifier: MPL-2.0
"""Service-manager feature contracts; managers retain their native semantics."""
from __future__ import annotations

from dataclasses import dataclass

@dataclass(frozen=True)
class ServiceManagerInfo:
    name: str
    can_list: bool
    can_inspect: bool
    mutations: tuple[str,...] = ()

SYSTEMD=ServiceManagerInfo("systemd",True,True,("start","stop","restart"))
LAUNCHD=ServiceManagerInfo("launchd",True,True,())

def manager_for(discovery: dict) -> ServiceManagerInfo | None:
    capabilities=discovery.get("capabilities",{})
    if capabilities.get("systemd",{}).get("available"): return SYSTEMD
    if capabilities.get("launchd",{}).get("available"): return LAUNCHD
    return None
