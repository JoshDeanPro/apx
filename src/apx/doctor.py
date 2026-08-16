# SPDX-License-Identifier: MPL-2.0
"""`apx doctor` -- find the things that make APX quietly wrong rather than loudly
broken.

The failures worth catching are mostly not "a command returned non-zero". They are
state living in a source checkout, a config copied from another machine that still
claims to be that machine, a stale runtime left behind by a previous installer, a
node running a different version from the rest of the fleet. Each finding carries
the fix, because a diagnosis you have to interpret is not much of a diagnosis.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any
import shutil
import sys

from .cloud import APX
from .config import apx_home, default_config_path, explain_self_host, is_source_checkout, load_document, state_files
from .protocol import MCPServer
from .selfupdate import installation
from .system import connection_status, scheduler_list, tailscale_status
from .foundation import inspect_foundation
from . import __version__

SEVERITIES = {"critical": 0, "problem": 1, "warning": 2}


def finding(identifier: str, severity: str, detail: str, fix: str = "") -> dict[str, str]:
    return {"id": identifier, "severity": severity, "detail": detail, "fix": fix}


def _check_installation(path: Path, report: dict[str, Any]) -> list[dict[str, str]]:
    """Is this installation put together the way an installation should be?"""
    found = []
    where = installation()
    report["installation"] = {**where, "home": str(apx_home())}
    if is_source_checkout(path):
        leaked = [p.name for p in state_files(path) if p.exists()]
        found.append(finding(
            "state_in_source_checkout", "problem",
            f"configuration and state live inside a source checkout ({path.parent})"
            + (f", including {', '.join(leaked)}" if leaked else ""),
            "run `apx config migrate` to move them to $APX_HOME",
        ))
    unused = Path.cwd()/"apx.toml"
    if unused.exists() and unused.resolve() != path.resolve():
        found.append(finding(
            "unused_config_in_working_directory", "warning",
            f"{unused} exists but is not the configuration in use ({path})",
            "pass --config explicitly, or move it into $APX_HOME",
        ))
    entrypoint = shutil.which("apx")
    if entrypoint:
        resolved = Path(entrypoint).resolve()
        if resolved.parent != Path(sys.executable).resolve().parent:
            found.append(finding(
                "entrypoint_mismatch", "warning",
                f"`apx` on PATH ({resolved}) belongs to a different environment than the running interpreter ({sys.executable})",
                "reinstall so `apx` points at one runtime, or remove the stale entrypoint",
            ))
    else:
        found.append(finding("apx_not_on_path", "problem", "`apx` is not on PATH", "add the installation's bin directory to PATH"))
    for stale in (Path.home()/".local/share/openpower", Path("/opt/openpower-agent")):
        if stale.exists() and where["kind"] != "development":
            found.append(finding(
                "legacy_runtime_present", "warning",
                f"a pre-APX OpenPower runtime is still installed at {stale}",
                f"remove {stale} once nothing references it",
            ))
    return found


def _check_identity(path: Path, cloud: APX, report: dict[str, Any]) -> list[dict[str, str]]:
    """Does this machine know which configured Node it is?"""
    try: _, raw = load_document(path)
    except Exception: return []
    targets = {name: host.target for name, host in cloud.hosts.items()}
    try: outcome = explain_self_host(raw, list(cloud.hosts), targets)
    except ValueError as error:
        return [finding("node_name_unknown", "critical", str(error), "correct `[node] name` to one of the configured hosts")]
    report["node"] = outcome
    if not outcome["name"]:
        return [finding(
            "node_unidentified", "problem",
            f"no configured host matches this machine (hostname {outcome.get('hostname')!r})",
            "add `[node] name = \"<host>\"` to the config",
        )]
    if not outcome["confident"]:
        return [finding(
            "node_identity_guessed", "warning",
            f"this machine is assumed to be {outcome['name']!r} only because it is the host declared `transport = \"local\"`; "
            f"the hostname is {outcome.get('hostname')!r}. A config copied from another machine will guess wrong.",
            f"add `[node] name = \"{outcome['name']}\"` to the config to state it explicitly",
        )]
    return []


def _check_fleet_versions(report: dict[str, Any]) -> list[dict[str, str]]:
    versions = {host["name"]: host.get("apx_version") for host in report["hosts"] if host.get("apx_version")}
    distinct = set(versions.values())
    if len(distinct) <= 1: return []
    return [finding(
        "version_skew", "warning",
        "nodes are running different APX versions: " + ", ".join(f"{name}={version}" for name, version in sorted(versions.items())),
        "run `apx update push` to bring the older nodes up to this one",
    )]


def diagnose(config: str | Path | None = None) -> dict[str,Any]:
    path=Path(config).expanduser() if config else default_config_path()
    foundation=inspect_foundation()
    report={"ok":True,"status":"healthy","versions":{"apx":__version__},"runtime":{"python":sys.version.split()[0],"executable":sys.executable,"isolated":sys.prefix!=getattr(sys,"base_prefix",sys.prefix)},"foundation":foundation,"config":{"path":str(path),"ok":False},"home":str(apx_home()),"hosts":[],"credentials":[],"connections":[],"plugins":[],"providers":[],"registry":{},"integrations":[],"databases":[],"mcp":{},"problems":[],"fixes":[]}
    report["problems"].extend(_check_installation(path,report))
    try:
        cloud=APX(path)
        report["config"]["ok"]=True
    except Exception as error:
        report["ok"]=False; report["status"]="misconfigured"; report["config"]["error"]=str(error)
        report["problems"].append(finding("config_unusable","critical",str(error),f"create or repair it with `apx init --output {path}`"))
        return _finish(report,foundation)
    report["problems"].extend(_check_identity(path,cloud,report))
    report["registry"]={"status":"healthy","actions":len(cloud.actions.list())}
    report["providers"]=[provider.health().to_dict() for provider in cloud.providers.values()]
    for host in cloud.hosts.values():
        item={"name":host.name,"transport":host.transport,"target":host.target,"reachable":False,"capabilities":[],"missing_optional":[]}
        try:
            info=cloud.core.host_info(host.name); item["reachable"]=True
            item["capabilities"]=sorted(name for name,value in info["capabilities"].items() if value["available"])
            item["service_manager"]="systemd" if info["capabilities"]["systemd"]["available"] else "launchd" if info["capabilities"]["launchd"]["available"] else None
            jobs=scheduler_list(host); item["schedulers"]={name:sum(1 for job in jobs["jobs"] if job["scheduler"]==name) for name in jobs["schedulers"]}
            item["connections"]=connection_status(host)
            if info["capabilities"]["tailscale"]["available"]:
                tailscale=tailscale_status(host); item["tailscale"]={"installed":True,"connected":tailscale.get("connected",False),"identity":tailscale.get("identity"),"peer_count":len(tailscale.get("peers",[])),"configured_connection_matches":tailscale.get("configured_connection_matches",[])}
            else: item["tailscale"]={"installed":False,"connected":False,"peer_count":0}
            for optional in ("git","rsync","scp"):
                if not info["capabilities"].get(optional,{}).get("available"): item["missing_optional"].append(optional)
            item["apx_version"]=_node_version(host)
        except Exception as error:
            item["error"]=str(error)
            report["problems"].append(finding(f"node_unreachable:{host.name}","problem",f"{host.name} is not reachable: {error}",
                                              f"check the transport for {host.name} (`apx inspect {host.name}`)"))
        report["hosts"].append(item)
    report["plugins"]=cloud.plugin_manager.health
    for name,metadata in sorted(cloud.plugin_manager.metadata.items()):
        health=next((item for item in report["plugins"] if item["name"]==name),{})
        report["integrations"].append({"name":name,"configured":health.get("configured",health.get("ok",False) and health.get("status")!="available_not_configured"),"status":health.get("status","ready" if health.get("ok") else "unhealthy"),"version":metadata.version_info.to_dict() if metadata.version_info else None,"actions":len(metadata.actions)})
    for value in cloud.config.get("databases",[]):
        report["databases"].append({key:value.get(key) for key in ("id","engine","host","port","provider","project","groups","tags") if value.get(key) is not None} | {"url_credential":value.get("url_credential"),"configured":True})
    report["connections"]=cloud.connection_health
    for connection in report["connections"]:
        if not connection["ok"]:
            report["problems"].append(finding(f"connection:{connection['id']}","problem",f"connection {connection['id']}: {connection['error']}",
                                              "repair or remove the connection in the config"))
    report["credentials"]=[]
    for credential_id in cloud.credentials.references:
        try:
            value=cloud.secrets.health(credential_id)
            report["credentials"].append({"id":credential_id,"available":bool(value.get("available")),"status":"healthy" if value.get("available") else "unavailable","source":value.get("source"),"lifecycle":value.get("lifecycle")})
        except Exception as error: report["credentials"].append({"id":credential_id,"available":False,"status":"misconfigured","error":str(error)})
    for credential in report["credentials"]:
        if not credential["available"]:
            report["problems"].append(finding(f"credential:{credential['id']}","problem",
                                              f"credential {credential['id']} is configured but its value cannot be read",
                                              f"set it with `apx secret set {credential['id']}`"))
    for plugin in report["plugins"]:
        if not plugin["ok"]:
            reason=plugin.get("error") or f"missing credential references: {', '.join(plugin.get('missing_credentials',[]))}"
            report["problems"].append(finding(f"plugin:{plugin['name']}","problem",f"plugin {plugin['name']}: {reason}",
                                              f"configure or disable it (`apx plugin {plugin['name']}`)"))
    try:
        tools=MCPServer(cloud).tools(); report["mcp"]={"available":True,"tools":len(tools)}
    except Exception as error:
        report["mcp"]={"available":False,"error":str(error)}
        report["problems"].append(finding("mcp_unavailable","problem",f"the MCP adapter could not build its tool list: {error}",
                                          "an Action in the registry is failing to describe itself; see `apx actions`"))
    report["problems"].extend(finding(f"event_listener:{e['owner']}","problem",f"event listener {e['owner']}: {e['error']}","")
                              for e in cloud.events.errors)
    report["problems"].extend(_check_fleet_versions(report))
    return _finish(report,foundation)


def _node_version(host) -> str | None:
    """What APX is actually installed on that Node -- asked, not assumed. Version skew
    across a fleet is invisible until something behaves differently on one machine."""
    from .transports import TransportError, transport_for
    try:
        result = transport_for(host).run(["apx", "--version"], timeout=20)
    except TransportError:
        return None
    return result.stdout.strip().removeprefix("APX ") if result.ok else None


def _finish(report: dict[str,Any], foundation: dict[str,Any]) -> dict[str,Any]:
    required_bad=[item for item in foundation["components"] if item["level"]=="foundation" and item["status"]!="healthy"]
    report["problems"].extend(finding(f"foundation:{item['id']}","critical",f"foundation component {item['id']}: {item['detail']}",
                                      f"install {item['id']}") for item in required_bad)
    report["problems"].sort(key=lambda item: SEVERITIES.get(item["severity"],9))
    report["fixes"]=[item["fix"] for item in report["problems"] if item["fix"]]
    blocking=[item for item in report["problems"] if item["severity"] in {"critical","problem"}]
    report["ok"]=not blocking
    report["status"]=("misconfigured" if any(item["severity"]=="critical" for item in report["problems"])
                      else "degraded" if blocking else "healthy")
    optional=[item["id"] for item in foundation["components"] if item["level"]=="optional" and item["status"]=="unavailable"]
    if optional: report["optional_missing"]=optional
    return report


def summarize(report: dict[str,Any]) -> str:
    """The default `apx doctor` output: what is wrong and what to do about it.

    The full report is a few hundred lines of inventory. Printing all of it every
    time trained everyone to skim past the four lines that mattered."""
    marks={"critical":"✗","problem":"✗","warning":"!"}
    hosts=report.get("hosts",[])
    reachable=[host for host in hosts if host.get("reachable")]
    lines=[f"apx {report['versions']['apx']}  ·  {report['status']}",
           f"config   {report['config']['path']}",
           f"node     {(report.get('node') or {}).get('name') or 'unidentified'}",
           f"nodes    {len(reachable)}/{len(hosts)} reachable" + (f" ({', '.join(h['name'] for h in hosts if not h.get('reachable'))} down)" if len(reachable)!=len(hosts) else ""),
           f"actions  {report.get('registry',{}).get('actions',0)}"]
    problems=report.get("problems",[])
    if not problems: return "\n".join(lines+["","no problems found"])
    lines.append("")
    for item in problems:
        lines.append(f"{marks.get(item['severity'],'-')} {item['detail']}")
        if item["fix"]: lines.append(f"  → {item['fix']}")
    return "\n".join(lines)
