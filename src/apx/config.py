# SPDX-License-Identifier: MIT
from __future__ import annotations

import os
import socket
import tomllib
from dataclasses import replace
from pathlib import Path

from platformdirs import user_config_path

from .models import Host, Project, ProjectLocation


# The installed runtime and the source checkout are two different things and must
# never share a directory. Everything an installation owns -- config.toml plus the
# `config.<store>.json` overlays derived from it (missions, grants, nodes, agents,
# actor credentials, ...) -- lives under APX_HOME. Source trees hold code, tests and
# spec only. Resolution therefore never consults the working directory: a checkout
# you happen to be standing in must not become the machine's configuration.
STATE_SUFFIXES = (
    ".groups.json", ".missions.json", ".blueprints.json", ".grants.json", ".nodes.json",
    ".agents.json", ".identity_links.json", ".enrollment.json", ".actor_credentials.json",
    ".state.json", ".prompts.json", ".shared_settings.json",
)


def apx_home() -> Path:
    """The installation's own directory: `$APX_HOME`, else `~/.config/apx`.

    Deliberately the same layout on macOS and Linux -- a fleet where every node
    keeps its state in the same place is one less thing to reason about, and the
    platform-native macOS location is only ever read as a legacy fallback."""
    explicit = os.environ.get("APX_HOME")
    return Path(explicit).expanduser() if explicit else Path.home()/".config/apx"


def default_config_path() -> Path:
    explicit = os.environ.get("APX_CONFIG")
    if explicit:
        return Path(explicit).expanduser()
    candidates = [apx_home()/"config.toml", user_config_path("apx")/"config.toml"]
    return next((path for path in candidates if path.exists()), candidates[0])


def is_source_checkout(path: Path) -> bool:
    """True when `path` sits inside a git working tree that carries APX's own source
    layout -- the signature of state that has leaked into a development checkout."""
    for directory in [path if path.is_dir() else path.parent, *path.parents]:
        if (directory/".git").exists():
            return (directory/"pyproject.toml").exists() and (directory/"src"/"apx").is_dir()
    return False


def state_files(config_path: Path) -> list[Path]:
    """Every sidecar an installation owns alongside `config_path`, present or not."""
    return [config_path.with_suffix(suffix) for suffix in STATE_SUFFIXES]


def migrate_into_home(source: Path, *, home: Path | None = None) -> dict:
    """Move a config file and its state overlays to `$APX_HOME/config.toml`.

    Used to lift state back out of a source checkout. Refuses rather than
    overwrites when the destination already exists, and moves the lock files
    with their stores so a concurrent writer cannot be left holding a lock on a
    path nothing reads any more."""
    source = Path(source).expanduser().resolve()
    destination_home = Path(home).expanduser() if home else apx_home()
    destination = destination_home/"config.toml"
    if destination.exists() and destination.resolve() != source:
        raise FileExistsError(f"{destination} already exists; move or remove it before migrating {source}")
    if destination.resolve() == source:
        return {"migrated": False, "reason": "already in place", "config": str(destination)}
    destination_home.mkdir(parents=True, exist_ok=True)
    moved = []
    for old, new in zip([source, *state_files(source)], [destination, *state_files(destination)]):
        for path, target in ((old, new), (Path(f"{old}.lock"), Path(f"{new}.lock"))):
            if path.exists():
                path.replace(target)
                moved.append({"from": str(path), "to": str(target)})
    return {"migrated": True, "config": str(destination), "moved": moved}


def load_document(path: str | Path | None = None) -> tuple[Path, dict]:
    source = Path(path).expanduser() if path else default_config_path()
    if not source.exists():
        raise FileNotFoundError(f"APX configuration not found: {source} (run `apx init` to create it)")
    return source,tomllib.loads(source.read_text(encoding="utf-8"))


def explain_self_host(raw: dict, names: list[str], targets: dict[str, str | None]) -> dict:
    """Which configured host is the machine we are running on, and how we know.

    The fleet topology is meant to be identical on every node -- one description of
    the whole graph, copied or synced around -- so the *only* machine-specific part
    is this one answer. In precedence order:

      1. `[node] name = "..."` in the config: explicit, and what `apx init` writes.
      2. `$APX_NODE`: an override for containers/images built from a shared config.
      3. This machine's hostname, matched against host names and SSH targets.
      4. The first host declared `transport = "local"`, for configs predating (1).

    Only (1)-(3) actually identify this machine; (4) is a guess that happens to be
    right on the machine a config was authored on and wrong on every copy of it, so
    it is reported as such and doctor flags it. A None answer is legitimate (a config
    describing a fleet this machine is not part of): every host is then remote.
    """
    declared = (raw.get("node") or {}).get("name") or os.environ.get("APX_NODE")
    if declared:
        if declared not in names:
            raise ValueError(f"node name {declared!r} is not one of the configured hosts: {', '.join(names)}")
        return {"name": declared, "method": "declared", "confident": True}
    hostname = socket.gethostname()
    for candidate in (hostname, hostname.split(".")[0], hostname.removesuffix(".local")):
        if candidate in names: return {"name": candidate, "method": "hostname", "confident": True, "hostname": hostname}
        matches = [name for name, target in targets.items() if target and target.split("@")[-1] == candidate]
        if len(matches) == 1: return {"name": matches[0], "method": "ssh_target", "confident": True, "hostname": hostname}
    guess = next((name for name in names if targets.get(name) is None and raw_transport(raw, name) == "local"), None)
    return {"name": guess, "method": "declared_local_fallback" if guess else "unresolved", "confident": False, "hostname": hostname}


def resolve_self_host(raw: dict, names: list[str], targets: dict[str, str | None]) -> str | None:
    return explain_self_host(raw, names, targets)["name"]


def raw_transport(raw: dict, name: str) -> str | None:
    for item in raw.get("hosts", []):
        if item.get("name") == name:
            connections = item.get("connections", ())
            primary = connections[0] if connections else {}
            return item.get("transport", primary.get("adapter", primary.get("transport", "local")))
    return None


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
    self_name = resolve_self_host(raw, list(hosts), {name: host.target for name, host in hosts.items()})
    # The machine we are on is reached locally, whatever the shared topology says
    # about how *other* nodes reach it -- otherwise a node SSHes to itself and its
    # own status depends on its own sshd being up.
    hosts = {
        name: replace(host, is_self=True, transport="local", target=None, connections=())
        if name == self_name else replace(host, is_self=False)
        for name, host in hosts.items()
    }
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
