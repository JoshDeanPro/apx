# SPDX-License-Identifier: MIT
from __future__ import annotations

from ...axp import Resource, VersionInfo

def discover(host: str, info: dict) -> Resource | None:
    capability=info.get("capabilities",{}).get("mysql",{})
    if not capability.get("available"): return None
    return Resource(f"technology:mysql:{host}","technology","MySQL client",{"host":host,"command":capability.get("command")},("mysql",),version=VersionInfo(compatibility="unknown",source="host discovery"))
