# SPDX-License-Identifier: MPL-2.0
"""Authoritative, capability-oriented description of the APX foundation."""
from __future__ import annotations

import platform
import shutil
import ssl
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from platformdirs import user_config_path, user_data_path, user_log_path, user_state_path

HEALTH_STATES=("healthy","degraded","unavailable","misconfigured")


@dataclass(frozen=True)
class FoundationComponent:
    id: str
    level: str
    capability: str
    reason: str
    commands: tuple[str,...]=()
    platforms: tuple[str,...]=( "Darwin","Linux")


COMPONENTS=(
    FoundationComponent("python","foundation","runtime.python","Runs the managed APX/OpenPower environment.",( "python3",)),
    FoundationComponent("tls","foundation","transport.https","Authenticates remote providers and update downloads."),
    FoundationComponent("git","recommended","project.version_control","Project inspection, plugins, rollback, and generated component history.",( "git",)),
    FoundationComponent("ssh","recommended","transport.ssh","Secure cross-machine APX transport using existing OpenSSH configuration.",( "ssh","ssh-agent")),
    FoundationComponent("rsync","optional","file.sync.optimized","Efficient incremental synchronization; file.copy remains available.",( "rsync",)),
    FoundationComponent("ripgrep","optional","search.fast","Fast project and context search with native fallbacks.",( "rg",)),
    FoundationComponent("curl","recommended","bootstrap.download","Installer bootstrap and operator diagnostics; APX HTTP uses its shared client.",( "curl",)),
)


def paths() -> dict[str,Path]:
    return {"config":user_config_path("apx"),"state":user_state_path("apx"),"data":user_data_path("apx"),"logs":user_log_path("apx")}


def inspect_foundation() -> dict[str,Any]:
    values=[]; system=platform.system()
    for component in COMPONENTS:
        if system not in component.platforms:
            state="unavailable"; detail="unsupported platform"
        elif component.id=="python":
            state="healthy" if sys.version_info>=(3,11) else "misconfigured"; detail=platform.python_version()
        elif component.id=="tls":
            verify=ssl.get_default_verify_paths(); available=bool(verify.cafile and Path(verify.cafile).exists()) or bool(verify.capath and Path(verify.capath).exists())
            state="healthy" if available else "misconfigured"; detail=verify.cafile or verify.capath or "no CA trust path"
        else:
            found={command:shutil.which(command) for command in component.commands}
            available=bool(found.get(component.commands[0]))
            state="healthy" if available else ("degraded" if component.level=="recommended" else "unavailable")
            detail=found
        values.append({**asdict(component),"status":state,"detail":detail})
    return {"platform":{"system":system,"architecture":platform.machine(),"python":platform.python_version()},"paths":{k:str(v) for k,v in paths().items()},"components":values}
