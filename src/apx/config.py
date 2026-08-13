# SPDX-License-Identifier: MPL-2.0
from __future__ import annotations

import os
import tomllib
from pathlib import Path

from platformdirs import user_config_path

from .models import Host, Project, ProjectLocation


def default_config_path() -> Path:
    explicit = os.environ.get("APX_CONFIG")
    if explicit:
        return Path(explicit).expanduser()
    candidates = [Path.cwd() / "apx.toml", Path.home()/".config/apx/config.toml", user_config_path("apx") / "config.toml"]
    return next((path for path in candidates if path.exists()), candidates[-1])


def load_document(path: str | Path | None = None) -> tuple[Path, dict]:
    source = Path(path).expanduser() if path else default_config_path()
    if not source.exists():
        raise FileNotFoundError(f"APX configuration not found: {source}")
    return source,tomllib.loads(source.read_text(encoding="utf-8"))


def load(path: str | Path | None = None) -> tuple[dict[str, Host], dict[str, Project]]:
    source,raw=load_document(path)
    hosts: dict[str, Host] = {}
    for item in raw.get("hosts", []):
        connections=tuple(item.get("connections",()))
        primary=connections[0] if connections else {}
        transport=item.get("transport",primary.get("adapter",primary.get("transport","local")))
        target=item.get("target",primary.get("target"))
        host = Host(item["name"],transport,target,connections,tuple(item.get("groups",())),tuple(item.get("tags",())),tuple(item.get("roles",())))
        if host.transport not in {"local", "ssh", "tailscale_ssh"}:
            raise ValueError(f"unsupported transport {host.transport!r} for {host.name}")
        if host.transport in {"ssh","tailscale_ssh"} and not host.target:
            raise ValueError(f"SSH host {host.name!r} requires target")
        for connection in connections:
            adapter=connection.get("adapter",connection.get("transport"))
            if adapter not in {"local","ssh","tailscale_ssh"}: raise ValueError(f"unsupported connection adapter {adapter!r} for {host.name}")
            if adapter in {"ssh","tailscale_ssh"} and not connection.get("target"): raise ValueError(f"connection {adapter!r} for {host.name} requires target")
        hosts[host.name] = host
    projects: dict[str, Project] = {}
    for item in raw.get("projects", []):
        project = Project(
            name=item["name"], description=item.get("description", ""),
            locations=tuple(ProjectLocation(**location) for location in item.get("locations", [])),
            services=tuple(item.get("services", [])), domains=tuple(item.get("domains", [])),
            context=item.get("context", {}),
            groups=tuple(item.get("groups",())), tags=tuple(item.get("tags",())),
        )
        projects[project.name] = project
    return hosts, projects
