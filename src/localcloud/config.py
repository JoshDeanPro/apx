from __future__ import annotations

import os
import tomllib
from pathlib import Path

from .models import Host, Project, ProjectLocation


def default_config_path() -> Path:
    explicit = os.environ.get("LOCALCLOUD_CONFIG")
    if explicit:
        return Path(explicit).expanduser()
    candidates = [Path.cwd() / "localcloud.toml", Path.home() / ".config/localcloud/config.toml"]
    return next((path for path in candidates if path.exists()), candidates[-1])


def load(path: str | Path | None = None) -> tuple[dict[str, Host], dict[str, Project]]:
    source = Path(path).expanduser() if path else default_config_path()
    if not source.exists():
        raise FileNotFoundError(f"LOCALCLOUD configuration not found: {source}")
    raw = tomllib.loads(source.read_text(encoding="utf-8"))
    hosts: dict[str, Host] = {}
    for item in raw.get("hosts", []):
        host = Host(item["name"], item.get("transport", "local"), item.get("target"))
        if host.transport not in {"local", "ssh"}:
            raise ValueError(f"unsupported transport {host.transport!r} for {host.name}")
        if host.transport == "ssh" and not host.target:
            raise ValueError(f"SSH host {host.name!r} requires target")
        hosts[host.name] = host
    projects: dict[str, Project] = {}
    for item in raw.get("projects", []):
        project = Project(
            name=item["name"], description=item.get("description", ""),
            locations=tuple(ProjectLocation(**location) for location in item.get("locations", [])),
            services=tuple(item.get("services", [])), domains=tuple(item.get("domains", [])),
            context=item.get("context", {}),
        )
        projects[project.name] = project
    return hosts, projects

