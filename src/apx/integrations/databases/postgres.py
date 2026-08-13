from __future__ import annotations

from ...axp import Resource, VersionInfo

def discover(host: str, info: dict) -> Resource | None:
    capability=info.get("capabilities",{}).get("postgres",{})
    if not capability.get("available"): return None
    return Resource(f"technology:postgres:{host}","technology","PostgreSQL client",{"host":host,"command":capability.get("command")},("psql",),version=VersionInfo(compatibility="unknown",source="host discovery"))
