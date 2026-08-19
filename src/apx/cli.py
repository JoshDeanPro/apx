# SPDX-License-Identifier: MIT
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Callable

from .cloud import APX
from .protocol import MCPServer
from .formatters import (
    print_json,
    render_actions_table,
    render_action_detail,
    render_resources_table,
    render_providers_table,
    render_whoami,
    render_policy_explain,
    render_action_result,
    render_conformance,
)
from . import __version__


def result_exit(result: Any) -> int:
    if getattr(result, "ok", False):
        return 0
    err = getattr(result, "error", None)
    code = err.code if hasattr(err, "code") else (err.get("code") if isinstance(err, dict) else "")
    status = getattr(result, "status", "")
    if status == "awaiting-approval":
        return 6
    if code in {"invalid_request", "unavailable"}:
        return 2
    if code == "permission_denied":
        return 3
    if code in {"capability_unavailable", "credential_revoked"}:
        return 4
    if code in {"connection_failure", "timeout"}:
        return 5
    if code in {"configuration_error", "authentication_required"}:
        return 7
    return 1


def emit(args: argparse.Namespace, raw_data: Any, formatter: Callable[[Any], None] | None = None) -> None:
    """Output either raw JSON (if --json is set) or human-friendly Rich formatting."""
    if getattr(args, "json", False) or formatter is None:
        if hasattr(raw_data, "to_dict"):
            raw_data = raw_data.to_dict()
        print_json(raw_data)
    else:
        formatter(raw_data)


def _main(argv: list[str] | None = None) -> int:
    effective_argv = list(sys.argv[1:] if argv is None else argv)
    if sys.stdin.isatty() and sys.stdout.isatty() and (
        not effective_argv or effective_argv == ["update"]
    ):
        from .node_ui import run_ui
        return run_ui(effective_argv)
    parser = argparse.ArgumentParser(
        prog="apx",
        description="APX: Universal Action Protocol & Capability Fabric",
    )
    parser.add_argument("--version", action="version", version=f"APX {__version__}")
    parser.add_argument("--config", help="TOML configuration path")
    parser.add_argument("--yes", action="store_true", help="confirm destructive actions")
    parser.add_argument("--actor", help="acting identity, e.g. human:operator (defaults to configured default_actor)")
    parser.add_argument("--json", action="store_true", help="output machine-readable JSON instead of formatted text")

    sub = parser.add_subparsers(dest="command", required=False)

    init = sub.add_parser("init", help="discover this machine and create minimal configuration")
    init.add_argument("--output", default=None, help="where to write the config (default: $APX_HOME/config.toml)")
    init.add_argument("--host", action="append", default=[], metavar="NAME=SSH_TARGET")
    init.add_argument("--non-interactive", "-y", "--yes", action="store_true", help="run non-interactively")
    init.add_argument("--force", action="store_true")
    init.add_argument("--json", action="store_true", help="output raw JSON")

    ver = sub.add_parser("version", help="report running APX version")
    ver.add_argument("--json", action="store_true", help="output raw JSON")

    security_p = sub.add_parser("security", help="offline security and privacy exposure checks")
    security_p.add_argument("verb", nargs="?", default="check", choices=["check"])
    security_p.add_argument("--json", action="store_true")

    serve = sub.add_parser("serve", help="expose full action registry over HTTP (APX Provider protocol)")
    serve.add_argument("--host", default="127.0.0.1")
    serve.add_argument("--port", type=int, default=8420)

    mcp = sub.add_parser("mcp", help="serve MCP over stdio (Model Context Protocol bridge)")
    mcp.add_argument("--actor", help="overrides global --actor for this MCP session")

    run = sub.add_parser("run", help="run any configured APX action")
    run.add_argument("action")
    run.add_argument("--input", default="{}", help="JSON object of action inputs")
    run.add_argument("--auth-context", help="JSON object asserting authenticated actor context")
    run.add_argument("--json", action="store_true", help="output raw JSON")

    sub.add_parser("plugins", help="list plugin metadata and health").add_argument("--json", action="store_true")
    plugin = sub.add_parser("plugin", help="inspect a plugin")
    plugin.add_argument("name")
    plugin.add_argument("--json", action="store_true")

    sub.add_parser("relationships", help="list resource relationships").add_argument("--json", action="store_true")
    sub.add_parser("resources", help="list APX resources").add_argument("--json", action="store_true")
    sub.add_parser("groups", help="list resource groups").add_argument("--json", action="store_true")
    group = sub.add_parser("group", help="inspect or change a group")
    group.add_argument("verb", choices=["show", "add", "remove"])
    group.add_argument("name")
    group.add_argument("resource", nargs="?")
    group.add_argument("--json", action="store_true")

    sub.add_parser("hosts", help="list configured hosts").add_argument("--json", action="store_true")
    inspect_p = sub.add_parser("inspect", help="discover a host")
    inspect_p.add_argument("host")
    inspect_p.add_argument("--json", action="store_true")

    status_p = sub.add_parser("status", help="read host status")
    status_p.add_argument("host")
    status_p.add_argument("--json", action="store_true")

    services_p = sub.add_parser("services", help="list services")
    services_p.add_argument("host")
    services_p.add_argument("--json", action="store_true")

    service_p = sub.add_parser("service", help="inspect or control a service")
    service_p.add_argument("verb", choices=["status", "start", "stop", "restart"])
    service_p.add_argument("host")
    service_p.add_argument("service")
    service_p.add_argument("--json", action="store_true")

    logs_p = sub.add_parser("logs", help="read journal logs")
    logs_p.add_argument("host")
    logs_p.add_argument("service", nargs="?")
    logs_p.add_argument("--lines", type=int, default=100)
    logs_p.add_argument("--json", action="store_true")

    copy_p = sub.add_parser("copy", help="copy one file between hosts")
    copy_p.add_argument("source_host")
    copy_p.add_argument("source")
    copy_p.add_argument("destination_host")
    copy_p.add_argument("destination")
    copy_p.add_argument("--json", action="store_true")

    sync_p = sub.add_parser("sync", help="sync paths with rsync")
    sync_p.add_argument("source_host")
    sync_p.add_argument("source")
    sync_p.add_argument("destination_host")
    sync_p.add_argument("destination")
    sync_p.add_argument("--apply", action="store_true", help="perform changes; default is dry-run")
    sync_p.add_argument("--json", action="store_true")

    sub.add_parser("projects", help="list configured projects").add_argument("--json", action="store_true")
    project_p = sub.add_parser("project", help="inspect a configured project")
    project_p.add_argument("name")
    project_p.add_argument("--json", action="store_true")

    discover_proj = sub.add_parser("discover-projects", help="discover repository/project directories")
    discover_proj.add_argument("host")
    discover_proj.add_argument("roots", nargs="*")
    discover_proj.add_argument("--json", action="store_true")

    shutdown_p = sub.add_parser("shutdown", help="shut down a host (requires --yes)")
    shutdown_p.add_argument("host")
    shutdown_p.add_argument("--json", action="store_true")

    sub.add_parser("fleet", help="parallel health probe over configured hosts").add_argument("--json", action="store_true")

    actions_p = sub.add_parser("actions", help="list the shared action catalog")
    actions_p.add_argument("--provider")
    actions_p.add_argument("--json", action="store_true")

    action_p = sub.add_parser("action", help="inspect an APX Action")
    action_p.add_argument("verb", choices=["inspect"])
    action_p.add_argument("name")
    action_p.add_argument("--provider")
    action_p.add_argument("--json", action="store_true")

    sub.add_parser("providers", help="list connected APX Action Providers").add_argument("--json", action="store_true")
    provider_p = sub.add_parser("provider", help="inspect a connected APX Action Provider")
    provider_p.add_argument("verb", choices=["inspect"])
    provider_p.add_argument("name")
    provider_p.add_argument("--json", action="store_true")

    discover_p = sub.add_parser("discover", help="identity-aware, policy-filtered capability discovery")
    discover_p.add_argument("subject", nargs="?", help="actor id to discover as")
    discover_p.add_argument("--namespace", action="append", default=[], dest="namespaces", metavar="NAMESPACE")
    discover_p.add_argument("--full", action="store_true", help="return full action definitions")
    discover_p.add_argument("--json", action="store_true")

    whoami_p = sub.add_parser("whoami", help="describe an actor and assigned roles")
    whoami_p.add_argument("target_actor", nargs="?", help="optional target actor to inspect")
    whoami_p.add_argument("--json", action="store_true")

    policy_p = sub.add_parser("policy", help="explain a policy decision")
    policy_p.add_argument("verb", choices=["explain"])
    policy_p.add_argument("action")
    policy_p.add_argument("--target-actor", help="actor to evaluate; defaults to --actor or default_actor")
    policy_p.add_argument("--target", action="append", default=[], metavar="KEY=VALUE")
    policy_p.add_argument("--json", action="store_true")

    state_p = sub.add_parser("state", help="show or change system/security state")
    state_p.add_argument("verb", choices=["show", "set"])
    state_p.add_argument("name", nargs="?")
    state_p.add_argument("--reason", default="")
    state_p.add_argument("--json", action="store_true")

    docs_p = sub.add_parser("docs", help="generate documentation for a project")
    docs_p.add_argument("project")
    docs_p.add_argument("--audience", choices=["human", "agent", "executive"], default="human")
    docs_p.add_argument("--json", action="store_true")

    secret_p = sub.add_parser("secret", help="inspect or change a secret")
    secret_p.add_argument("verb", choices=["list", "get", "set", "reveal", "rotate", "health"])
    secret_p.add_argument("id", nargs="?")
    secret_p.add_argument("--json", action="store_true")

    mission_p = sub.add_parser("mission", help="manage Missions (desired outcomes)")
    mission_p.add_argument("verb", choices=["list", "create", "show", "start", "complete", "block", "cancel", "verify", "resume", "grant", "docs"])
    mission_p.add_argument("id", nargs="?")
    mission_p.add_argument("--project")
    mission_p.add_argument("--title")
    mission_p.add_argument("--objective")
    mission_p.add_argument("--description", default="")
    mission_p.add_argument("--owner")
    mission_p.add_argument("--priority", default="normal")
    mission_p.add_argument("--scope", action="append", default=[])
    mission_p.add_argument("--constraints", action="append", default=[])
    mission_p.add_argument("--criteria", action="append", default=[])
    mission_p.add_argument("--related-resources", action="append", default=[])
    mission_p.add_argument("--reason", default="")
    mission_p.add_argument("--status")
    mission_p.add_argument("--grantee")
    mission_p.add_argument("--grant-action")
    mission_p.add_argument("--audience", choices=["human", "agent", "executive"], default="human")
    mission_p.add_argument("--json", action="store_true")

    task_p = sub.add_parser("task", help="manage Tasks derived from a Mission")
    task_p.add_argument("verb", choices=["list", "create", "propose", "show", "start", "complete", "block", "cancel", "verify", "claim", "release"])
    task_p.add_argument("id", nargs="?")
    task_p.add_argument("--mission")
    task_p.add_argument("--title")
    task_p.add_argument("--reason")
    task_p.add_argument("--objective", default="")
    task_p.add_argument("--dependencies", action="append", default=[])
    task_p.add_argument("--related-resources", action="append", default=[])
    task_p.add_argument("--criteria", action="append", default=[])
    task_p.add_argument("--proposals-json")
    task_p.add_argument("--claimant")
    task_p.add_argument("--status")
    task_p.add_argument("--json", action="store_true")

    blueprint_p = sub.add_parser("blueprint", help="manage Blueprints")
    blueprint_p.add_argument("verb", choices=["list", "show", "plan", "apply", "upgrade", "status", "search"])
    blueprint_p.add_argument("id", nargs="?")
    blueprint_p.add_argument("--version")
    blueprint_p.add_argument("--project")
    blueprint_p.add_argument("--inputs-json")
    blueprint_p.add_argument("--query")
    blueprint_p.add_argument("--category")
    blueprint_p.add_argument("--tag")
    blueprint_p.add_argument("--json", action="store_true")

    grant_p = sub.add_parser("grant", help="issue/inspect/revoke Grants")
    grant_p.add_argument("verb", choices=["issue", "list", "show", "revoke"])
    grant_p.add_argument("id", nargs="?")
    grant_p.add_argument("--subject")
    grant_p.add_argument("--action", action="append", dest="actions", default=[])
    grant_p.add_argument("--resource", action="append", dest="resources", default=[])
    grant_p.add_argument("--constraints-json")
    grant_p.add_argument("--reason", default="")
    grant_p.add_argument("--expires-at")
    grant_p.add_argument("--include-expired", action="store_true")
    grant_p.add_argument("--json", action="store_true")

    adapter_p = sub.add_parser("adapter", help="APX Adapter conformance")
    adapter_p.add_argument("verb", choices=["test"])
    adapter_p.add_argument("--url")
    adapter_p.add_argument("--provider")
    adapter_p.add_argument("--bridge")
    adapter_p.add_argument("--json", action="store_true")

    conformance_p = sub.add_parser("conformance", help="run full APX protocol conformance test suite")
    conformance_p.add_argument("--url")
    conformance_p.add_argument("--json", action="store_true")

    daemon_p = sub.add_parser("daemon", help="manage background socket daemon")
    daemon_p.add_argument("verb", choices=["status", "start", "stop", "restart"])
    daemon_p.add_argument("--json", action="store_true")

    node_p = sub.add_parser("node", help="hardware-aware Node profiles")
    node_p.add_argument("verb", choices=["list", "show", "refresh", "permissions"])
    node_p.add_argument("host", nargs="?")
    node_p.add_argument("--subject")
    node_p.add_argument("--json", action="store_true")

    search_p = sub.add_parser("search", help="deterministic local search")
    search_p.add_argument("query")
    search_p.add_argument("--kind", action="append", dest="kinds", default=[])
    search_p.add_argument("--limit", type=int, default=20)
    search_p.add_argument("--json", action="store_true")

    sub.add_parser("work", help="what is this actor currently supposed to be doing").add_argument("--json", action="store_true")

    auth_p = sub.add_parser("auth", help="authentication status / authenticate")
    auth_p.add_argument("verb", choices=["status", "authenticate"])
    auth_p.add_argument("--method", default="local")
    auth_p.add_argument("--token")
    auth_p.add_argument("--json", action="store_true")

    identity_p = sub.add_parser("identity", help="manage Principals, links, enrollment")
    identity_p.add_argument("verb", choices=["list", "show", "link", "unlink", "enroll-request", "enroll-status", "enroll-approve", "enroll-deny", "enroll-cancel", "pair-create", "pair-claim"])
    identity_p.add_argument("target", nargs="?")
    identity_p.add_argument("--external-subject")
    identity_p.add_argument("--openpower-subject")
    identity_p.add_argument("--external-ref")
    identity_p.add_argument("--openpower-ref")
    identity_p.add_argument("--machine-id")
    identity_p.add_argument("--runtime")
    identity_p.add_argument("--requested-roles", action="append", default=[])
    identity_p.add_argument("--requested-scopes", action="append", default=[])
    identity_p.add_argument("--device-fingerprint")
    identity_p.add_argument("--claimant")
    identity_p.add_argument("--ttl", type=int, default=300)
    identity_p.add_argument("--json", action="store_true")

    cred_p = sub.add_parser("credential", help="manage ActorCredentials")
    cred_p.add_argument("verb", choices=["issue", "show", "rotate", "confirm-rotation", "revoke"])
    cred_p.add_argument("id", nargs="?")
    cred_p.add_argument("--principal")
    cred_p.add_argument("--type", default="opaque_bearer")
    cred_p.add_argument("--issuer", default="local")
    cred_p.add_argument("--expires")
    cred_p.add_argument("--fingerprint")
    cred_p.add_argument("--secret-ref")
    cred_p.add_argument("--json", action="store_true")

    hw_p = sub.add_parser("hardware", help="on-device hardware and accelerator compute capacity awareness")
    hw_p.add_argument("--json", action="store_true", help="output JSON hardware profile")

    settings_p = sub.add_parser("settings", help="manage APX settings and runtime options")
    settings_p.add_argument("verb", nargs="?", default="show", choices=["show", "get", "set", "list"])
    settings_p.add_argument("key", nargs="?")
    settings_p.add_argument("value", nargs="?")
    settings_p.add_argument("--json", action="store_true", help="output JSON settings")

    create_p = sub.add_parser("create", help="scaffold an extension")
    create_p.add_argument("kind", choices=["plugin", "action", "adapter"])
    create_p.add_argument("name")
    create_p.add_argument("--output", default=None)
    create_p.add_argument("--json", action="store_true")

    config_p = sub.add_parser("config", help="show configuration and state locations")
    config_p.add_argument("verb", nargs="?", default="show", choices=["show", "migrate"])
    config_p.add_argument("--source")
    config_p.add_argument("--json", action="store_true")

    prompt_p = sub.add_parser("prompt", help="manage saved, shared, and scoped prompts")
    prompt_p.add_argument("verb", nargs="?", default="list", choices=["list", "inspect", "create", "update", "assign", "delete"])
    prompt_p.add_argument("id", nargs="?")
    prompt_p.add_argument("--title")
    prompt_p.add_argument("--content")
    prompt_p.add_argument("--description", default="")
    prompt_p.add_argument("--scope", default="shared")
    prompt_p.add_argument("--target", action="append", default=[])
    prompt_p.add_argument("--tag", action="append", default=[])
    prompt_p.add_argument("--json", action="store_true")

    sub.add_parser("prompts", help="list saved and shared prompts").add_argument("--json", action="store_true")

    shared_set_p = sub.add_parser("shared-settings", help="manage hierarchical scoped settings")
    shared_set_p.add_argument("verb", nargs="?", default="list", choices=["list", "get", "set"])
    shared_set_p.add_argument("key", nargs="?")
    shared_set_p.add_argument("value", nargs="?")
    shared_set_p.add_argument("--scope", default="shared")
    shared_set_p.add_argument("--target-scope")
    shared_set_p.add_argument("--group")
    shared_set_p.add_argument("--description", default="")
    shared_set_p.add_argument("--target", action="append", default=[])
    shared_set_p.add_argument("--json", action="store_true")

    args = parser.parse_args(argv)

    # 1. Zero arguments -> Launch Interactive TUI if on an interactive terminal
    if args.command is None:
        if sys.stdin.isatty() and sys.stdout.isatty():
            from .tui import run_tui
            return run_tui(config_path=args.config, actor=args.actor)
        parser.print_help()
        return 0

    # 2. Standalone simple commands
    if args.command == "version":
        if getattr(args, "json", False):
            print_json({"version": __version__})
        else:
            print(f"APX {__version__}")
        return 0

    if args.command == "init":
        from .setup import initialize
        from .config import apx_home
        destination = Path(args.output).expanduser() if args.output else apx_home() / "config.toml"
        try:
            res = initialize(destination, ssh_hosts=args.host, interactive=not args.non_interactive, force=args.force)
            if getattr(args, "json", False):
                print_json(res)
            else:
                print(f"✓ APX initialized at {destination}")
            return 0
        except Exception as error:
            print_json({"ok": False, "error": str(error)})
            return 1

    if args.command == "hardware":
        from .hardware import inspect_hardware
        hw = inspect_hardware()
        if getattr(args, "json", False):
            print_json(hw)
        else:
            print(f"[APX On-Device Hardware Profile: {hw.get('node_id', 'local')}]")
            print(f" • Compute Tier:      {hw.get('compute_tier')}")
            print(f" • CPU:               {hw.get('cpu', {}).get('model')} ({hw.get('cpu', {}).get('cores')} cores, {hw.get('cpu', {}).get('architecture')})")
            print(f" • Memory:            {hw.get('memory', {}).get('total_gb')} GB total ({hw.get('memory', {}).get('available_gb')} GB available)")
            print(f" • Accelerators:      Metal: {hw.get('accelerators', {}).get('metal')} | ANE: {hw.get('accelerators', {}).get('neural_engine')} | CUDA: {hw.get('accelerators', {}).get('cuda')}")
            print(f" • Storage:           {hw.get('storage', {}).get('free_gb')} GB free / {hw.get('storage', {}).get('total_gb')} GB total ({hw.get('storage', {}).get('percent_free')}% free)")
            print(f" • Recommendations:   Allow Local LLM: {hw.get('recommendations', {}).get('allow_local_llm')} | Standing Agent: {hw.get('recommendations', {}).get('allow_background_standing_agent')}")
        return 0

    if args.command == "settings":
        from .settings import format_settings, get_all_settings, get_setting, set_setting
        if args.verb == "get":
            if not args.key:
                print_json({"ok": False, "error": "missing setting key for get"})
                return 2
            val = get_setting(args.key, args.config)
            if getattr(args, "json", False):
                print_json({args.key: val})
            else:
                print(val if val is not None else "")
            return 0
        if args.verb == "set":
            if not args.key or args.value is None:
                print_json({"ok": False, "error": "missing key or value for set"})
                return 2
            res = set_setting(args.key, args.value, args.config)
            print_json(res)
            return 0
        all_settings = get_all_settings(args.config)
        if getattr(args, "json", False) or args.verb == "list":
            print_json(all_settings)
        else:
            print(format_settings(all_settings))
        return 0

    if args.command == "create":
        from .scaffold import create as create_ext
        try:
            res = create_ext(args.kind, args.name, args.output)
            emit(args, res)
            return 0
        except Exception as error:
            print_json({"ok": False, "error": str(error)})
            return 1

    if args.command == "config":
        from .config import apx_home, default_config_path, is_source_checkout, migrate_into_home, state_files
        resolved = Path(args.config).expanduser() if args.config else default_config_path()
        if args.verb == "migrate":
            source = Path(args.source).expanduser() if args.source else resolved
            try:
                res = migrate_into_home(source)
                print_json(res)
                return 0
            except Exception as error:
                print_json({"ok": False, "error": str(error)})
                return 1
        data = {
            "home": str(apx_home()),
            "config": str(resolved),
            "exists": resolved.exists(),
            "in_source_checkout": is_source_checkout(resolved),
            "state": [str(path) for path in state_files(resolved) if path.exists()],
        }
        print_json(data)
        return 0

    if args.command == "security":
        from .security import check
        report = check(args.config)
        if getattr(args, "json", False):
            print_json(report)
        else:
            print("APX security check")
            for finding in report["checks"]:
                print(f"{finding['severity']}: {finding['message']} — {finding['next_action']}")
            if not report["checks"]:
                print("PASS: no configured exposure warnings found")
            print("Model: local checks reduce accidental disclosure; they do not provide process or OS sandboxing")
        return 0 if report["ok"] else 2

    try:
        cloud = APX(args.config)
    except Exception as error:
        print_json({"ok": False, "error": str(error)})
        return 1

    if args.command in {"prompts", "prompt"}:
        if args.command == "prompts" or args.verb == "list":
            res = cloud.run("prompt.list", actor=args.actor, scope=getattr(args, "scope", None))
        elif args.verb == "inspect":
            res = cloud.run("prompt.inspect", actor=args.actor, prompt_id=args.id)
        elif args.verb == "create":
            res = cloud.run("prompt.create", actor=args.actor, title=args.title or args.id, content=args.content or "", description=args.description, scope=args.scope, targets=args.target, tags=args.tag)
        elif args.verb == "update":
            res = cloud.run("prompt.update", actor=args.actor, prompt_id=args.id, title=args.title, content=args.content, description=args.description, scope=args.scope, targets=args.target, tags=args.tag)
        elif args.verb == "assign":
            res = cloud.run("prompt.assign", actor=args.actor, prompt_id=args.id, targets=args.target)
        else:
            res = cloud.run("prompt.delete", actor=args.actor, prompt_id=args.id)
        emit(args, res.to_dict())
        return result_exit(res)

    if args.command == "shared-settings":
        if args.verb == "get":
            res = cloud.run("settings.scoped.get", actor=args.actor, key=args.key, target_scope=args.target_scope, group=args.group)
        elif args.verb == "set":
            res = cloud.run("settings.scoped.set", actor=args.actor, key=args.key, value=args.value, scope=args.scope, description=args.description, targets=args.target)
        else:
            res = cloud.run("settings.scoped.list", actor=args.actor, target_scope=args.target_scope, group=args.group)
        emit(args, res.to_dict())
        return result_exit(res)

    if args.command == "plugins":
        data = {"plugins": [cloud.plugin_manager.inspect(name) for name in sorted(cloud.plugin_manager.metadata)]}
        emit(args, data)
        return 0

    if args.command == "plugin":
        try:
            data = cloud.plugin_manager.inspect(args.name)
            emit(args, data)
            return 0
        except KeyError as error:
            print_json({"ok": False, "error": str(error)})
            return 1

    if args.command == "fleet":
        result = cloud.run("fleet.health", actor=args.actor)
        emit(args, result.to_dict(), lambda d: render_action_result(result))
        return 0 if result.ok and result.result.get("healthy") else result_exit(result)

    if args.command == "relationships":
        data = {"relationships": [item.to_dict() for item in cloud.relationships()]}
        emit(args, data)
        return 0

    if args.command == "resources":
        emit(args, {"resources": [item.to_dict() for item in cloud.resources()]}, lambda d: render_resources_table(cloud.resources()))
        return 0

    if args.command == "groups":
        emit(args, cloud.group_list())
        return 0

    if args.command == "group":
        if args.verb == "show":
            emit(args, cloud.group_inspect(args.name))
            return 0
        if not args.resource:
            print_json({"ok": False, "error": "resource is required for group add/remove"})
            return 2
        result = cloud.run(f"group.{args.verb}", actor=args.actor, resource=args.resource, group=args.name)
        emit(args, result.to_dict())
        return result_exit(result)

    if args.command == "mcp":
        return MCPServer(cloud, actor=args.actor).serve()

    if args.command == "serve":
        from .httpserver import serve as serve_http
        serve_http(cloud, host=args.host, port=args.port)
        return 0

    if args.command == "actions":
        actions_list = [a for a in cloud.actions.list() if not args.provider or a.provider == args.provider]
        values = [a.definition().to_dict() for a in actions_list]
        emit(args, {"actions": values}, lambda d: render_actions_table(actions_list))
        return 0

    if args.command == "providers":
        manifests = cloud.provider_manifests()
        values = [{"id": m.provider.id, "name": m.provider.name, "url": m.provider.url, "actions": len(m.actions), "profiles": list(m.profiles)} for m in manifests]
        emit(args, {"providers": values}, lambda d: render_providers_table(manifests))
        return 0

    if args.command == "provider":
        manifest = next((m for m in cloud.provider_manifests() if m.provider.id == args.name), None)
        if not manifest:
            print_json({"ok": False, "error": f"unknown provider {args.name!r}"})
            return 1
        emit(args, manifest.to_dict())
        return 0

    if args.command == "action":
        try:
            definition = cloud.actions.get(args.name).definition()
        except Exception as error:
            print_json({"ok": False, "error": str(error)})
            return 1
        if args.provider and definition.provider != args.provider:
            print_json({"ok": False, "error": "action is not supplied by requested provider"})
            return 1
        emit(args, definition.to_dict(), lambda d: render_action_detail(definition))
        return 0

    if args.command == "whoami":
        result = cloud.run("actor.whoami", actor=args.actor, subject=args.target_actor or args.actor)
        emit(args, result.to_dict(), lambda d: render_whoami(result.result if result.ok else result.to_dict()))
        return result_exit(result)

    if args.command == "policy":
        target = {}
        for pair in args.target:
            if "=" not in pair:
                print_json({"ok": False, "error": f"--target must be KEY=VALUE, got {pair!r}"})
                return 2
            key, value = pair.split("=", 1)
            target[key] = value
        result = cloud.run("policy.explain", actor=args.actor, subject=args.target_actor, requested_action=args.action, scope=target)
        emit(args, result.to_dict(), lambda d: render_policy_explain(result.result if result.ok else result.to_dict()))
        return result_exit(result)

    if args.command == "conformance":
        from .conformance import check_conformance
        if args.url:
            result = cloud.run("adapter.test", actor=args.actor, url=args.url)
            emit(args, result.to_dict())
            return result_exit(result)
        report = check_conformance(cloud)
        emit(args, report, lambda d: render_conformance(report))
        return 0

    if args.command == "run":
        try:
            inputs = json.loads(args.input)
            if not isinstance(inputs, dict):
                raise ValueError("--input must be a JSON object")
            auth_context = json.loads(args.auth_context) if args.auth_context else None
            action = cloud.actions.get(args.action)
            if action.destructive and not args.yes:
                print_json({"action": args.action, "ok": False, "error": "destructive action requires --yes"})
                return 2
            confirmation = {"level": action.confirmation, "confirmed": True, "authorization_id": f"cli:{action.name}"} if args.yes and action.confirmation != "none" else None
            result = cloud.run(args.action, actor=args.actor, confirmation=confirmation, auth_context=auth_context, **inputs)
            emit(args, result.to_dict(), lambda d: render_action_result(result))
            return result_exit(result)
        except (json.JSONDecodeError, ValueError) as error:
            print_json({"action": args.action, "ok": False, "error": str(error)})
            return 2
        except Exception as error:
            print_json({"action": args.action, "ok": False, "error": str(error)})
            return 1

    if args.command == "state":
        if args.verb == "show":
            result = cloud.run("state.show", actor=args.actor)
            emit(args, result.to_dict())
            return result_exit(result)
        if not args.name:
            print_json({"ok": False, "error": "name is required for state set"})
            return 2
        result = cloud.run("state.set", actor=args.actor, name=args.name, reason=args.reason, changed_by=args.actor)
        emit(args, result.to_dict())
        return result_exit(result)

    if args.command == "docs":
        result = cloud.run("docs.generate", actor=args.actor, project=args.project, audience=args.audience)
        if not result.ok:
            emit(args, result.to_dict())
            return result_exit(result)
        print(result.result["content"])
        return 0

    if args.command == "secret":
        import getpass
        if args.verb in {"get", "reveal", "rotate", "health"} and not args.id:
            print_json({"ok": False, "error": f"id is required for secret {args.verb}"})
            return 2
        if args.verb == "set":
            if not args.id:
                print_json({"ok": False, "error": "id is required for secret set"})
                return 2
            value = getpass.getpass("Secret value: ") if sys.stdin.isatty() else sys.stdin.readline().rstrip("\n")
            result = cloud.run("secret.set", actor=args.actor, id=args.id, value=value)
        else:
            result = cloud.run(f"secret.{args.verb}", actor=args.actor, id=args.id)
        emit(args, result.to_dict())
        return result_exit(result)

    if args.command == "mission":
        v = args.verb
        if v == "list":
            result = cloud.run("mission.list", actor=args.actor, project=args.project, status=args.status)
        elif v == "create":
            if not (args.project and args.title and args.objective):
                print_json({"ok": False, "error": "--project, --title, and --objective are required for mission create"})
                return 2
            result = cloud.run("mission.create", actor=args.actor, project=args.project, title=args.title, objective=args.objective, description=args.description, owner=args.owner, priority=args.priority, scope=args.scope, constraints=args.constraints, success_criteria=args.criteria, related_resources=args.related_resources)
        elif not args.id:
            print_json({"ok": False, "error": f"mission id is required for mission {v}"})
            return 2
        elif v == "show":
            result = cloud.run("mission.inspect", actor=args.actor, mission=args.id)
        elif v in {"start", "complete"}:
            result = cloud.run(f"mission.{v}", actor=args.actor, mission=args.id, changed_by=args.actor)
        elif v in {"block", "cancel"}:
            result = cloud.run(f"mission.{v}", actor=args.actor, mission=args.id, reason=args.reason, changed_by=args.actor)
        elif v == "verify":
            result = cloud.run("mission.verify", actor=args.actor, mission=args.id, criteria_met=args.criteria, verified_by=args.actor)
        elif v == "resume":
            result = cloud.run("mission.resume", actor=args.actor, mission=args.id)
        elif v == "grant":
            if not (args.grantee and args.grant_action):
                print_json({"ok": False, "error": "--grantee and --grant-action are required for mission grant"})
                return 2
            result = cloud.run("mission.grant", actor=args.actor, mission=args.id, grantee=args.grantee, action=args.grant_action)
        else:
            result = cloud.run("mission.docs", actor=args.actor, mission=args.id, audience=args.audience)
            if not result.ok:
                emit(args, result.to_dict())
                return result_exit(result)
            print(result.result["content"])
            return 0
        emit(args, result.to_dict())
        return result_exit(result)

    if args.command == "task":
        v = args.verb
        if v == "list":
            result = cloud.run("task.list", actor=args.actor, mission=args.mission, status=args.status, assigned_actor=args.claimant)
        elif v == "create":
            if not (args.mission and args.title and args.reason):
                print_json({"ok": False, "error": "--mission, --title, and --reason are required for task create"})
                return 2
            result = cloud.run("task.create", actor=args.actor, mission=args.mission, title=args.title, reason=args.reason, objective=args.objective, dependencies=args.dependencies, related_resources=args.related_resources, acceptance_criteria=args.criteria)
        elif v == "propose":
            if not (args.mission and args.proposals_json):
                print_json({"ok": False, "error": "--mission and --proposals-json are required for task propose"})
                return 2
            try:
                proposals = json.loads(args.proposals_json)
            except json.JSONDecodeError as error:
                print_json({"ok": False, "error": f"--proposals-json must be valid JSON: {error}"})
                return 2
            result = cloud.run("task.propose", actor=args.actor, mission=args.mission, proposals=proposals)
        elif not args.id:
            print_json({"ok": False, "error": f"task id is required for task {v}"})
            return 2
        elif v == "show":
            result = cloud.run("task.inspect", actor=args.actor, task=args.id)
        elif v in {"start", "complete"}:
            result = cloud.run(f"task.{v}", actor=args.actor, task=args.id, changed_by=args.actor)
        elif v in {"block", "cancel"}:
            result = cloud.run(f"task.{v}", actor=args.actor, task=args.id, reason=args.reason, changed_by=args.actor)
        elif v == "verify":
            result = cloud.run("task.verify", actor=args.actor, task=args.id, criteria_met=args.criteria, verified_by=args.actor)
        elif v in {"claim", "release"}:
            result = cloud.run(f"task.{v}", actor=args.actor, task=args.id, claimant=args.claimant or args.actor)
        emit(args, result.to_dict())
        return result_exit(result)

    if args.command == "blueprint":
        v = args.verb
        if v == "list":
            result = cloud.run("blueprint.list", actor=args.actor, category=args.category, tag=args.tag)
        elif v == "search":
            result = cloud.run("blueprint.search", actor=args.actor, query=args.query, category=args.category, tag=args.tag)
        elif v == "status":
            if not args.project:
                print_json({"ok": False, "error": "--project is required for blueprint status"})
                return 2
            result = cloud.run("blueprint.status", actor=args.actor, project=args.project)
        elif not args.id:
            print_json({"ok": False, "error": f"a blueprint name is required for blueprint {v}"})
            return 2
        elif v == "show":
            result = cloud.run("blueprint.show", actor=args.actor, blueprint=args.id, version=args.version)
        else:
            try:
                blueprint_inputs = json.loads(args.inputs_json) if args.inputs_json else {}
            except json.JSONDecodeError as error:
                print_json({"ok": False, "error": f"--inputs-json is not valid JSON: {error}"})
                return 2
            if v == "plan":
                result = cloud.run("blueprint.plan", actor=args.actor, blueprint=args.id, version=args.version, project=args.project, inputs=blueprint_inputs)
            else:
                if v == "upgrade" and not args.project:
                    print_json({"ok": False, "error": "--project is required for blueprint upgrade"})
                    return 2
                if not args.yes:
                    print_json({"ok": False, "error": f"blueprint {v} requires --yes"})
                    return 2
                action = cloud.actions.get(f"blueprint.{v}")
                confirmation = {"level": action.confirmation, "confirmed": True, "authorization_id": f"cli:blueprint.{v}:{args.id}"}
                if v == "apply":
                    result = cloud.run("blueprint.apply", actor=args.actor, confirmation=confirmation, blueprint=args.id, version=args.version, project=args.project, inputs=blueprint_inputs)
                else:
                    result = cloud.run("blueprint.upgrade", actor=args.actor, confirmation=confirmation, blueprint=args.id, project=args.project, inputs=blueprint_inputs)
        emit(args, result.to_dict())
        return result_exit(result)

    if args.command == "discover":
        result = cloud.run("discovery.capabilities", actor=args.actor, subject=args.subject or args.actor, namespaces=args.namespaces, compact=not args.full)
        emit(args, result.to_dict())
        return result_exit(result)

    if args.command == "grant":
        v = args.verb
        if v == "issue":
            if not (args.subject and args.actions):
                print_json({"ok": False, "error": "--subject and at least one --action are required for grant issue"})
                return 2
            try:
                constraints = json.loads(args.constraints_json) if args.constraints_json else {}
            except json.JSONDecodeError as error:
                print_json({"ok": False, "error": f"--constraints-json is not valid JSON: {error}"})
                return 2
            result = cloud.run("grant.issue", actor=args.actor, subject=args.subject, actions=args.actions, resources=args.resources, constraints=constraints, reason=args.reason, expires_at=args.expires_at)
        elif v == "list":
            result = cloud.run("grant.list", actor=args.actor, subject=args.subject, include_expired=args.include_expired)
        elif not args.id:
            print_json({"ok": False, "error": f"a grant id is required for grant {v}"})
            return 2
        elif v == "show":
            result = cloud.run("grant.inspect", actor=args.actor, grant=args.id)
        else:
            result = cloud.run("grant.revoke", actor=args.actor, grant=args.id)
        emit(args, result.to_dict())
        return result_exit(result)

    if args.command == "adapter":
        if not (args.url or args.provider or args.bridge):
            print_json({"ok": False, "error": "one of --url, --provider, or --bridge is required for adapter test"})
            return 2
        result = cloud.run("adapter.test", actor=args.actor, url=args.url, provider=args.provider, bridge=args.bridge)
        emit(args, result.to_dict())
        return result_exit(result)

    if args.command == "daemon":
        from .daemon import daemon_socket_path, is_daemon_running, start_daemon_background, stop_daemon
        if args.verb == "status":
            running = is_daemon_running()
            emit(args, {"running": running, "socket": str(daemon_socket_path())})
            return 0 if running else 1
        if args.verb == "start":
            res = start_daemon_background(args.config)
            emit(args, res)
            return 0 if res.get("ok") else 1
        if args.verb == "stop":
            res = stop_daemon()
            emit(args, res)
            return 0
        if args.verb == "restart":
            stop_daemon()
            res = start_daemon_background(args.config)
            emit(args, res)
            return 0 if res.get("ok") else 1

    if args.command == "node":
        v = args.verb
        if v == "list":
            result = cloud.run("node.list", actor=args.actor)
        elif not args.host:
            print_json({"ok": False, "error": f"a host is required for node {v}"})
            return 2
        elif v == "show":
            result = cloud.run("node.inspect", actor=args.actor, host=args.host)
        elif v == "refresh":
            result = cloud.run("node.refresh", actor=args.actor, host=args.host)
        else:
            result = cloud.run("node.permissions", actor=args.actor, host=args.host, subject=args.subject or args.actor)
        emit(args, result.to_dict())
        return result_exit(result)

    if args.command == "search":
        result = cloud.run("search.query", actor=args.actor, query=args.query, kinds=args.kinds, limit=args.limit)
        emit(args, result.to_dict())
        return result_exit(result)

    if args.command == "work":
        result = cloud.run("work.current", actor=args.actor, subject=args.subject or args.actor)
        emit(args, result.to_dict())
        return result_exit(result)

    if args.command == "auth":
        if args.verb == "status":
            result = cloud.run("auth.status", actor=args.actor)
        else:
            credentials = {"token": args.token} if args.token else {"principal_id": args.actor}
            result = cloud.run("auth.authenticate", actor=args.actor, method=args.method, credentials=credentials)
        emit(args, result.to_dict())
        return result_exit(result)

    if args.command == "identity":
        v = args.verb
        if v == "list":
            result = cloud.run("identity.list", actor=args.actor)
        elif v == "enroll-request":
            if not (args.machine_id and args.runtime):
                print_json({"ok": False, "error": "--machine-id and --runtime are required for identity enroll-request"})
                return 2
            result = cloud.run("identity.enrollment.request", actor=args.actor, machine_id=args.machine_id, runtime=args.runtime, principal=args.target, requested_roles=args.requested_roles, requested_scopes=args.requested_scopes, device_fingerprint=args.device_fingerprint)
        elif v == "pair-create":
            result = cloud.run("identity.pairing.create", actor=args.actor, ttl_seconds=args.ttl)
        elif v == "pair-claim":
            if not (args.target and args.claimant):
                print_json({"ok": False, "error": "a pairing code and --claimant are required for identity pair-claim"})
                return 2
            result = cloud.run("identity.pairing.claim", actor=args.actor, code=args.target, claimant=args.claimant)
        elif not args.target:
            print_json({"ok": False, "error": f"a target (subject/request id) is required for identity {v}"})
            return 2
        elif v == "show":
            result = cloud.run("identity.inspect", actor=args.actor, subject=args.target)
        elif v == "link":
            target_sub = args.external_subject or args.openpower_subject
            if not target_sub:
                print_json({"ok": False, "error": "--external-subject is required for identity link"})
                return 2
            result = cloud.run("identity.link", actor=args.actor, subject=args.target, external_subject=target_sub, linked_by=args.actor)
        elif v == "unlink":
            result = cloud.run("identity.unlink", actor=args.actor, subject=args.target, unlinked_by=args.actor)
        elif v == "enroll-status":
            result = cloud.run("identity.enrollment.status", actor=args.actor, request_id=args.target)
        elif v == "enroll-cancel":
            result = cloud.run("identity.enrollment.cancel", actor=args.actor, request_id=args.target, cancelled_by=args.actor)
        elif v == "enroll-approve":
            ref = args.external_ref or args.openpower_ref
            result = cloud.run("identity.enrollment.approve", actor=args.actor, request_id=args.target, approved_by=args.actor, external_ref=ref)
        else:
            result = cloud.run("identity.enrollment.deny", actor=args.actor, request_id=args.target, denied_by=args.actor)
        emit(args, result.to_dict())
        return result_exit(result)

    if args.command == "credential":
        v = args.verb
        if v == "issue":
            if not args.principal:
                print_json({"ok": False, "error": "--principal is required for credential issue"})
                return 2
            result = cloud.run("credential.issue", actor=args.actor, principal=args.principal, type=args.type, issuer=args.issuer, expires=args.expires, fingerprint=args.fingerprint, secret_ref=args.secret_ref)
        elif not args.id:
            print_json({"ok": False, "error": f"a credential id is required for credential {v}"})
            return 2
        elif v == "show":
            result = cloud.run("credential.inspect", actor=args.actor, credential_id=args.id)
        elif v == "rotate":
            result = cloud.run("credential.rotate", actor=args.actor, credential_id=args.id, fingerprint=args.fingerprint, secret_ref=args.secret_ref)
        elif v == "confirm-rotation":
            result = cloud.run("credential.confirm_rotation", actor=args.actor, previous_credential_id=args.id)
        else:
            result = cloud.run("credential.revoke", actor=args.actor, credential_id=args.id, revoked_by=args.actor)
        emit(args, result.to_dict())
        return result_exit(result)

    if args.command == "service":
        name = f"service.{args.verb}"
        inputs = {"host": args.host, "service": args.service}
    elif args.command == "hosts":
        name, inputs = "host.list", {}
    elif args.command == "inspect":
        name, inputs = "host.inspect", {"host": args.host}
    elif args.command == "status":
        name, inputs = "host.status", {"host": args.host}
    elif args.command == "services":
        name, inputs = "service.list", {"host": args.host}
    elif args.command == "logs":
        name, inputs = "logs.read", {"host": args.host, "service": args.service, "lines": args.lines}
    elif args.command == "projects":
        name, inputs = "project.list", {}
    elif args.command == "project":
        name, inputs = "project.inspect", {"project": args.name}
    elif args.command == "discover-projects":
        name, inputs = "project.discover", {"host": args.host, "roots": args.roots or None}
    elif args.command == "copy":
        name, inputs = "file.copy", {"source_host": args.source_host, "source": args.source, "destination_host": args.destination_host, "destination": args.destination}
    elif args.command == "sync":
        name, inputs = "file.sync", {"source_host": args.source_host, "source": args.source, "destination_host": args.destination_host, "destination": args.destination, "dry_run": not args.apply}
    else:
        name, inputs = "host.shutdown", {"host": args.host}

    action = cloud.actions.get(name)
    if action.destructive and not args.yes:
        print_json({"action": name, "ok": False, "error": "destructive action requires --yes"})
        return 2
    confirmation = {"level": action.confirmation, "confirmed": True, "authorization_id": f"cli:{name}"} if args.yes and action.confirmation != "none" else None
    result = cloud.run(name, actor=args.actor, confirmation=confirmation, **inputs)
    emit(args, result.to_dict(), lambda d: render_action_result(result))
    return 0 if result.ok else result_exit(result)


def _cleanup() -> None:
    """Centralized cleanup to prevent stale state, locks, and broken terminals."""
    try:
        # Restore terminal state explicitly if needed outside of prompt_toolkit
        if sys.stdout.isatty():
            sys.stdout.write("\033[?25h")  # Show cursor
            sys.stdout.flush()
    except Exception:
        pass


def main(argv: list[str] | None = None) -> int:
    import signal
    def handle_sigterm(*args):
        _cleanup()
        sys.exit(143)
    
    signal.signal(signal.SIGTERM, handle_sigterm)
    
    try:
        return _main(argv)
    except (KeyboardInterrupt, EOFError):
        return 130
    finally:
        _cleanup()


if __name__ == "__main__":
    sys.exit(main())
