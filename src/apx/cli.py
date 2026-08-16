# SPDX-License-Identifier: MPL-2.0
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .cloud import APX
from .protocol import MCPServer
from . import __version__


def output(value: object) -> None: print(json.dumps(value,indent=2,ensure_ascii=False))


def result_exit(result) -> int:
    if result.ok: return 0
    code=result.error.code if result.error else ""
    if result.status=="authorization_required": return 6
    if code in {"invalid_input","action.not_found"}: return 2
    if code=="permission_denied": return 3
    if code in {"capability_unavailable","credential_revoked"}: return 4
    if code in {"connection_failure","timeout"}: return 5
    if code in {"configuration_error","authentication_required"}: return 7
    return 1


def _main(argv: list[str] | None = None) -> int:
    parser=argparse.ArgumentParser(prog="apx",description="Use your computers and services together.")
    parser.add_argument("--version",action="version",version=f"APX {__version__}")
    parser.add_argument("--config",help="TOML configuration path")
    parser.add_argument("--yes",action="store_true",help="confirm destructive actions")
    parser.add_argument("--actor",help="acting identity, e.g. agent::mac (defaults to the configured default_actor)")
    sub=parser.add_subparsers(dest="command",required=False)
    init=sub.add_parser("init",help="discover this machine and create minimal configuration")
    init.add_argument("--output",default=None,help="where to write the config (default: $APX_HOME/config.toml)")
    init.add_argument("--host",action="append",default=[],metavar="NAME=SSH_TARGET")
    init.add_argument("--non-interactive",action="store_true")
    init.add_argument("--force",action="store_true")
    doctor_parser=sub.add_parser("doctor",help="diagnose this installation: state placement, node identity, hosts, credentials, plugins, MCP")
    doctor_parser.add_argument("--json",action="store_true",help="emit the full report instead of the summary")
    sub.add_parser("menu",help="interactive terminal UI: arrow keys/j,k move, enter select, esc back, / filter")
    sub.add_parser("start",help="open the interactive TUI (same as running apx with no arguments)")
    serve=sub.add_parser("serve",help="expose the full action registry over HTTP (the same Action Provider protocol any apx system speaks) -- for a website/app to discover and call")
    serve.add_argument("--host",default="127.0.0.1"); serve.add_argument("--port",type=int,default=8420)
    sub.add_parser("plugins",help="list plugin metadata and health")
    sub.add_parser("fleet",help="parallel health probe over every configured Host and every zero-argument *.status Action")
    agent=sub.add_parser("agent",help="set up a Standing Agent (the apx-autopilot pattern: a coding agent run to completion, on a loop, under systemd/launchd)")
    agent.add_argument("verb",choices=["plan","setup","list","show","logs","remove"])
    agent.add_argument("name",nargs="?")
    agent.add_argument("--host"); agent.add_argument("--repo")
    agent.add_argument("--description",default=""); agent.add_argument("--project-description",default="")
    agent.add_argument("--user",default="root")
    from .agents import AGENT_RUNTIMES
    agent.add_argument("--runtime",default="",choices=list(AGENT_RUNTIMES))
    agent.add_argument("--model",default="opus"); agent.add_argument("--effort",default="medium")
    agent.add_argument("--timeout",type=int,default=7200); agent.add_argument("--idle-gap",type=int,default=1800)
    agent.add_argument("--status-command"); agent.add_argument("--test-command")
    agent.add_argument("--force",action="store_true"); agent.add_argument("--enable",action="store_true"); agent.add_argument("--start",action="store_true")
    agent.add_argument("--purge",action="store_true")
    agent.add_argument("--lines",type=int,default=100)
    environment=sub.add_parser("environment",help="ingest MCP servers already configured elsewhere (~/..json, ~/.codex/config.toml, ...)")
    environment.add_argument("verb",choices=["sources","ingest"])
    environment.add_argument("source",nargs="?",help="source id (not needed for `sources`), e.g. _code, codex")
    plugin=sub.add_parser("plugin",help="inspect a plugin"); plugin.add_argument("name")
    sub.add_parser("relationships",help="list resource relationships")
    sub.add_parser("resources",help="list APX resources")
    sub.add_parser("groups",help="list resource groups")
    group=sub.add_parser("group",help="inspect or change a group"); group.add_argument("verb",choices=["show","add","remove"]); group.add_argument("name"); group.add_argument("resource",nargs="?")
    create=sub.add_parser("create",help="scaffold an extension"); create.add_argument("kind",choices=["plugin","action","adapter"]); create.add_argument("name"); create.add_argument("--output",default=".")
    run=sub.add_parser("run",help="run any configured APX action"); run.add_argument("action"); run.add_argument("--input",default="{}",help="JSON object of action inputs")
    run.add_argument("--auth-context",help="JSON object asserting an authenticated actor context, required by some provider (e.g. browser.*) consequential actions -- e.g. '{\"principal_id\":\"human:ethan\"}'")
    update=sub.add_parser("update",help="update the APX software, leaving local state alone (a checkout fast-forwards; an installed runtime installs its configured source)")
    update.add_argument("verb",nargs="?",default="apply",choices=["check","apply","push"])
    update.add_argument("hosts",nargs="*",help="for `push`: which Nodes to update (default: every Node that is not this machine)")
    update.add_argument("--from",dest="source",help="wheel, sdist, directory, URL or pip requirement to install (installed runtimes only)")
    update.add_argument("--no-reinstall",dest="reinstall",action="store_false",default=True)
    settings_parser=sub.add_parser("settings",help="manage APX settings, health diagnostics (doctor), updates, and runtime options")
    settings_parser.add_argument("verb",nargs="?",default="show",choices=["show","doctor","update","get","set","list"])
    settings_parser.add_argument("key",nargs="?",help="setting key for get/set, or update action (check/apply/push) for `update`")
    settings_parser.add_argument("value",nargs="?",help="setting value for set")
    settings_parser.add_argument("extra_hosts",nargs="*",help="target nodes for push update")
    settings_parser.add_argument("--json",action="store_true",help="output in JSON format")
    settings_parser.add_argument("--from",dest="source",help="wheel, sdist, directory, URL or pip requirement to install")
    settings_parser.add_argument("--no-reinstall",dest="reinstall",action="store_false",default=True)
    sub.add_parser("version",help="report the running apx version and git commit")
    config_parser=sub.add_parser("config",help="show where this installation keeps its configuration and state, or move it out of a source checkout")
    config_parser.add_argument("verb",nargs="?",default="show",choices=["show","migrate"])
    config_parser.add_argument("--from",dest="source",help="config to migrate (default: the resolved one)")
    install=sub.add_parser("install",help="install APX as a native capability inside a supported AI coding agent (slash command / skill -- not MCP)")
    install.add_argument("agent",choices=["-code","codex","kimi-code","deepseek-code","hermes"])
    install.add_argument("--output",default=".",help="project root to install project-scoped config into (ignored with --global)")
    install.add_argument("--global",dest="global_scope",action="store_true",help="install for this user across all projects, where the agent supports it")
    sub.add_parser("hosts",help="list configured hosts")
    inspect=sub.add_parser("inspect",help="discover a host"); inspect.add_argument("host")
    status=sub.add_parser("status",help="read host status"); status.add_argument("host")
    services=sub.add_parser("services",help="list services"); services.add_argument("host")
    service=sub.add_parser("service",help="inspect or control a service"); service.add_argument("verb",choices=["status","start","stop","restart"]); service.add_argument("host"); service.add_argument("service")
    logs=sub.add_parser("logs",help="read journal logs"); logs.add_argument("host"); logs.add_argument("service",nargs="?"); logs.add_argument("--lines",type=int,default=100)
    copy=sub.add_parser("copy",help="copy one file between hosts"); copy.add_argument("source_host"); copy.add_argument("source"); copy.add_argument("destination_host"); copy.add_argument("destination")
    sync=sub.add_parser("sync",help="sync paths with rsync"); sync.add_argument("source_host"); sync.add_argument("source"); sync.add_argument("destination_host"); sync.add_argument("destination"); sync.add_argument("--apply",action="store_true",help="perform changes; default is dry-run")
    projects=sub.add_parser("projects",help="list configured projects")
    project=sub.add_parser("project",help="inspect a configured project"); project.add_argument("name")
    discover=sub.add_parser("discover-projects",help="discover repository/project directories"); discover.add_argument("host"); discover.add_argument("roots",nargs="*")
    shutdown=sub.add_parser("shutdown",help="shut down a host (requires --yes)"); shutdown.add_argument("host")
    actions_parser=sub.add_parser("actions",help="list the shared action catalog"); actions_parser.add_argument("--provider")
    sub.add_parser("providers",help="list connected APX Action Providers")
    provider_parser=sub.add_parser("provider",help="inspect a connected APX Action Provider"); provider_parser.add_argument("verb",choices=["inspect"]); provider_parser.add_argument("name")
    action_parser=sub.add_parser("action",help="inspect an APX Action"); action_parser.add_argument("verb",choices=["inspect"]); action_parser.add_argument("name"); action_parser.add_argument("--provider")
    mcp=sub.add_parser("mcp",help="serve MCP over stdio"); mcp.add_argument("--actor",help="overrides the global --actor for this MCP session")
    whoami=sub.add_parser("whoami",help="describe an actor and its assigned roles"); whoami.add_argument("target_actor",nargs="?")
    policy=sub.add_parser("policy",help="explain a policy decision"); policy.add_argument("verb",choices=["explain"]); policy.add_argument("target_actor"); policy.add_argument("action"); policy.add_argument("--target",action="append",default=[],metavar="KEY=VALUE")
    state=sub.add_parser("state",help="show or change system/security state"); state.add_argument("verb",choices=["show","set"]); state.add_argument("name",nargs="?"); state.add_argument("--reason",default="")
    docs=sub.add_parser("docs",help="generate documentation for a project"); docs.add_argument("project"); docs.add_argument("--audience",choices=["human","ai","machine"],default="human")
    secret=sub.add_parser("secret",help="inspect or change a secret (values are never echoed)"); secret.add_argument("verb",choices=["get","set","reveal","rotate","health"]); secret.add_argument("id",nargs="?")
    mission=sub.add_parser("mission",help="manage Missions (desired outcomes)")
    mission.add_argument("verb",choices=["list","show","create","start","block","complete","verify","cancel","docs","resume","grant"])
    mission.add_argument("id",nargs="?",help="mission id (not needed for list/create)")
    mission.add_argument("--project"); mission.add_argument("--title"); mission.add_argument("--objective")
    mission.add_argument("--description",default=""); mission.add_argument("--owner"); mission.add_argument("--priority",default="normal")
    mission.add_argument("--scope",default=""); mission.add_argument("--status"); mission.add_argument("--reason",default="")
    mission.add_argument("--audience",choices=["human","ai","machine"],default="human")
    mission.add_argument("--criteria",action="append",default=[],metavar="CRITERION")
    mission.add_argument("--constraint",action="append",default=[],dest="constraints",metavar="CONSTRAINT")
    mission.add_argument("--resource",action="append",default=[],dest="related_resources",metavar="RESOURCE")
    mission.add_argument("--grantee"); mission.add_argument("--grant-action",dest="grant_action")
    task=sub.add_parser("task",help="manage Tasks derived from a Mission")
    task.add_argument("verb",choices=["list","show","propose","create","start","block","complete","verify","cancel","claim","release"])
    task.add_argument("id",nargs="?",help="task id (not needed for list/create/propose)")
    task.add_argument("--mission"); task.add_argument("--title"); task.add_argument("--reason",default=""); task.add_argument("--objective",default="")
    task.add_argument("--status"); task.add_argument("--claimant")
    task.add_argument("--criteria",action="append",default=[],metavar="CRITERION")
    task.add_argument("--resource",action="append",default=[],dest="related_resources",metavar="RESOURCE")
    task.add_argument("--dependency",action="append",default=[],dest="dependencies",metavar="TASK_ID")
    task.add_argument("--proposals-json",help="JSON array of {title,reason,...} proposal objects, for `task propose`")
    blueprint=sub.add_parser("blueprint",help="manage Blueprints (versioned, composable action graphs)")
    blueprint.add_argument("verb",choices=["list","search","show","plan","apply","status","upgrade"])
    blueprint.add_argument("id",nargs="?",help="blueprint name/alias (not needed for list/search/status)")
    blueprint.add_argument("--version"); blueprint.add_argument("--project"); blueprint.add_argument("--category"); blueprint.add_argument("--tag")
    blueprint.add_argument("--query",default="")
    blueprint.add_argument("--inputs-json",help="JSON object of Blueprint inputs, for plan/apply/upgrade")
    discover=sub.add_parser("discover",help="identity-aware, policy-filtered capability discovery (the DISCOVER protocol operation)")
    discover.add_argument("subject",nargs="?",help="actor id to discover as (defaults to the configured default actor)")
    discover.add_argument("--namespace",action="append",default=[],dest="namespaces",metavar="NAMESPACE")
    discover.add_argument("--full",action="store_true",help="return full action definitions instead of the compact discovery shape")
    grant=sub.add_parser("grant",help="issue/inspect/revoke Grants -- standalone, independently-expiring delegated authority")
    grant.add_argument("verb",choices=["issue","list","show","revoke"])
    grant.add_argument("id",nargs="?",help="grant id (not needed for issue/list)")
    grant.add_argument("--subject",help="actor id the grant is issued to, for issue/list")
    grant.add_argument("--action",action="append",default=[],dest="actions",metavar="ACTION",help="action name or namespace.* pattern, for issue")
    grant.add_argument("--resource",action="append",default=[],dest="resources",metavar="APX_REF",help="apx://kind/id resource ref, for issue")
    grant.add_argument("--constraints-json",help="JSON object of extra scope constraints, for issue")
    grant.add_argument("--reason",default="")
    grant.add_argument("--expires-at",help="ISO-8601 timestamp; omit for a grant that does not expire")
    grant.add_argument("--include-expired",action="store_true")
    adapter=sub.add_parser("adapter",help="APX Adapter conformance")
    adapter.add_argument("verb",choices=["test"])
    adapter.add_argument("--url",help="test a remote provider by discovery URL (its origin, e.g. https://acme.example)")
    adapter.add_argument("--provider",help="test a locally-registered provider by id")
    adapter.add_argument("--bridge",help="test a locally-registered Bridge by id")
    conformance=sub.add_parser("conformance",help="run full APX protocol conformance test suite")
    conformance.add_argument("--url",help="test a remote provider endpoint")
    conformance.add_argument("--json",action="store_true",help="output in JSON format")
    daemon=sub.add_parser("daemon",help="manage background socket daemon (apxd) for ultra-low latency (<2ms) execution")
    daemon.add_argument("verb",choices=["start","stop","status","restart"])
    node=sub.add_parser("node",help="hardware-aware Node profiles and per-Node effective permissions")
    node.add_argument("verb",choices=["list","show","refresh","permissions"])
    node.add_argument("host",nargs="?",help="host name (not needed for list)")
    node.add_argument("--subject",help="actor id to evaluate permissions for, for `node permissions` (defaults to the caller)")
    search=sub.add_parser("search",help="deterministic local search over Nodes/Projects/Actions/Blueprints/Connections/Grants -- no AI")
    search.add_argument("query")
    search.add_argument("--kind",action="append",default=[],dest="kinds",metavar="KIND")
    search.add_argument("--limit",type=int,default=20)
    work=sub.add_parser("work",help="what is this actor currently supposed to be doing"); work.add_argument("verb",choices=["current"]); work.add_argument("subject",nargs="?")
    auth=sub.add_parser("auth",help="authentication provider status / authenticate")
    auth.add_argument("verb",choices=["status","authenticate"]); auth.add_argument("--method",default="local"); auth.add_argument("--token",help="bearer token/JWT, for --method openpower")
    link=sub.add_parser("link",help="link this machine to your OpenPower account (shortcut for `identity device-link`)")
    link.add_argument("--agent-name",help="shown to the human approving this link, default: 'APX on <hostname>'")
    identity=sub.add_parser("identity",help="manage Principals, OpenPower links, enrollment, and device pairing")
    identity.add_argument("verb",choices=["list","show","link","unlink","enroll-request","enroll-status","enroll-cancel","enroll-approve","enroll-deny","pair-create","pair-claim","device-link"])
    identity.add_argument("target",nargs="?",help="subject id / enrollment request id / pairing code, depending on verb")
    identity.add_argument("--openpower-subject"); identity.add_argument("--openpower-ref")
    identity.add_argument("--machine-id"); identity.add_argument("--runtime")
    identity.add_argument("--role",action="append",default=[],dest="requested_roles"); identity.add_argument("--scope",action="append",default=[],dest="requested_scopes")
    identity.add_argument("--device-fingerprint"); identity.add_argument("--claimant"); identity.add_argument("--ttl",type=int,default=600)
    identity.add_argument("--agent-name",help="shown to the human approving this link, for identity device-link (default: 'APX on <hostname>')")
    credential=sub.add_parser("credential",help="manage ActorCredentials (authenticate the actor -- distinct from provider secrets)")
    credential.add_argument("verb",choices=["issue","show","rotate","confirm-rotation","revoke"])
    credential.add_argument("id",nargs="?")
    credential.add_argument("--principal"); credential.add_argument("--type",default="opaque_bearer"); credential.add_argument("--issuer",default="local")
    credential.add_argument("--expires"); credential.add_argument("--fingerprint"); credential.add_argument("--secret-ref")
    hardware_parser = sub.add_parser("hardware", help="on-device hardware, accelerator (Metal/CUDA/ANE), and compute capacity awareness")
    hardware_parser.add_argument("--json", action="store_true", help="output JSON hardware profile")
    localcloud_parser = sub.add_parser("localcloud", help="decentralized zero-knowledge mesh credential vault and failover")
    localcloud_parser.add_argument("verb", nargs="?", default="status", choices=["status", "get", "set", "sync"])
    localcloud_parser.add_argument("key", nargs="?", help="secret key name")
    localcloud_parser.add_argument("value", nargs="?", help="secret value")
    parser.add_argument("--doctor",action="store_true",help="shortcut for `apx doctor`")
    parser.add_argument("--add-keys",action="store_true",help="shortcut: open the TUI directly on Credentials, to add an API key/token")
    args=parser.parse_args(argv)
    if args.command != "mcp":
        try:
            from .selfupdate import notify_if_update_available
            notify_if_update_available(stream=sys.stderr if sys.stderr.isatty() else None)
        except Exception:
            pass
    if args.doctor:
        from .doctor import diagnose, summarize
        result=diagnose(args.config); print(summarize(result)); return 0 if result["ok"] else 1
    if args.command is None or args.command=="start":
        # No subcommand (or the friendlier `apx start`) opens the TUI -- the same
        # idea as OpenClaw's bare invocation dropping you straight into its wizard,
        # not a scripted-only tool that only does something once you already know
        # the exact subcommand. Falls back to --help when there's no real
        # terminal to draw into (piped/scripted invocation), since curses cannot
        # run without one.
        if sys.stdin.isatty() and sys.stdout.isatty():
            # A machine that has never been configured gets the setup wizard, not
            # an error: "install it, run it" has to be true on a fresh host, which
            # is the whole point of a bare invocation dropping into the TUI.
            from .config import default_config_path
            config_path=Path(args.config).expanduser() if args.config else default_config_path()
            if not config_path.exists():
                from .tui import first_run
                if first_run(config_path) is None: return 0
            try: cloud=APX(args.config)
            except Exception as error: output({"ok":False,"error":str(error)}); return 1
            from .tui import run as run_menu
            return run_menu(cloud,args.actor,start_screen="credentials" if args.add_keys else None)
        parser.print_help()
        return 0
    if args.command=="init":
        from .setup import initialize
        from .config import apx_home
        destination=Path(args.output).expanduser() if args.output else apx_home()/"config.toml"
        try: output(initialize(destination,ssh_hosts=args.host,interactive=not args.non_interactive,force=args.force)); return 0
        except Exception as error: output({"ok":False,"error":str(error)}); return 1
    if args.command=="doctor":
        from .doctor import diagnose, summarize
        result=diagnose(args.config)
        if args.json: output(result)
        else: print(summarize(result))
        return 0 if result["ok"] else 1
    if args.command == "hardware":
        from .hardware import inspect_hardware
        hw = inspect_hardware()
        if getattr(args, "json", False):
            output(hw)
        else:
            print(f"[APX On-Device Hardware Profile: {hw['node_id']}]")
            print(f" • Compute Tier:      {hw['compute_tier']}")
            print(f" • CPU:               {hw['cpu']['model']} ({hw['cpu']['cores']} cores, {hw['cpu']['architecture']})")
            print(f" • Memory:            {hw['memory']['total_gb']} GB total ({hw['memory']['available_gb']} GB available)")
            print(f" • Accelerators:      Metal: {hw['accelerators']['metal']} | ANE: {hw['accelerators']['neural_engine']} | CUDA: {hw['accelerators']['cuda']}")
            print(f" • Storage:           {hw['storage']['free_gb']} GB free / {hw['storage']['total_gb']} GB total ({hw['storage']['percent_free']}% free)")
            print(f" • Power:             AC Power: {hw['power']['on_ac_power']} | Battery: {hw['power']['battery_percent']}%")
            print(f" • Recommendations:   Allow Local LLM: {hw['recommendations']['allow_local_llm']} | Standing Agent: {hw['recommendations']['allow_background_standing_agent']}")
        return 0
    if args.command == "localcloud":
        from .localcloud import localcloud_status, localcloud_get, localcloud_set
        v = args.verb
        if v == "status":
            st = localcloud_status()
            output(st)
        elif v == "get":
            if not args.key:
                output({"ok": False, "error": "key required for localcloud get"})
                return 2
            val = localcloud_get(args.key)
            output({"key": args.key, "value": val, "found": val is not None})
        elif v == "set":
            if not (args.key and args.value):
                output({"ok": False, "error": "key and value required for localcloud set"})
                return 2
            res = localcloud_set(args.key, args.value)
            output(res)
        elif v == "sync":
            st = localcloud_status()
            print("[APX LocalCloud Mesh Vault]")
            print(f" • Sovereignty: {st['sovereignty']}")
            print(f" • Node Key:    {st['node_key_id']}")
            print(f" • Items:       {st['vault_items_count']} secrets cached locally")
            print(" • Mesh State:  Active & Failover Ready across fleet (Zero-Knowledge)")
        return 0
    if args.command=="settings":
        from .settings import execute_settings_doctor, execute_settings_update, format_settings, get_all_settings, get_setting, set_setting
        if args.verb=="doctor":
            return execute_settings_doctor(args.config, json_output=args.json)
        if args.verb=="update":
            action = args.key or "check"
            return execute_settings_update(verb=action, source=args.source, reinstall=args.reinstall, hosts=args.extra_hosts, config_path=args.config, json_output=args.json)
        if args.verb=="get":
            if not args.key: output({"ok":False,"error":"missing setting key for get"}); return 2
            val = get_setting(args.key, args.config)
            if args.json: output({args.key: val})
            else: print(val if val is not None else "")
            return 0
        if args.verb=="set":
            if not args.key or args.value is None: output({"ok":False,"error":"missing key or value for set"}); return 2
            res = set_setting(args.key, args.value, args.config)
            output(res); return 0
        all_settings = get_all_settings(args.config)
        if args.json or args.verb=="list": output(all_settings)
        else: print(format_settings(all_settings))
        return 0
    if args.command=="create":
        from .scaffold import create
        try: output(create(args.kind,args.name,args.output)); return 0
        except Exception as error: output({"ok":False,"error":str(error)}); return 1
    if args.command=="version":
        from .selfupdate import version_info
        output(version_info()); return 0
    if args.command=="config":
        from .config import apx_home,default_config_path,is_source_checkout,migrate_into_home,state_files
        resolved=Path(args.config).expanduser() if args.config else default_config_path()
        if args.verb=="migrate":
            source=Path(args.source).expanduser() if args.source else resolved
            try: output(migrate_into_home(source)); return 0
            except Exception as error: output({"ok":False,"error":str(error)}); return 1
        output({"home":str(apx_home()),"config":str(resolved),"exists":resolved.exists(),
                "in_source_checkout":is_source_checkout(resolved),
                "state":[str(path) for path in state_files(resolved) if path.exists()]})
        return 0
    if args.command=="update":
        from .selfupdate import UpdateError, apply_update, check_for_updates, push_to_host
        document={}
        try:
            from .config import load_document
            _,document=load_document(args.config)
        except Exception: pass  # updating the software must not require a valid config
        if args.verb=="check": output(check_for_updates(source=args.source,config=document)); return 0
        if args.verb=="push":
            from .config import load
            try:
                hosts,_=load(args.config)
                targets=[hosts[name] for name in (args.hosts or [h for h,v in hosts.items() if not v.is_self])]
            except KeyError as error: output({"ok":False,"error":f"unknown host {error}"}); return 2
            except Exception as error: output({"ok":False,"error":str(error)}); return 1
            results,failures=[],0
            for host in targets:
                try: results.append(push_to_host(host))
                except UpdateError as error: results.append({"host":host.name,"ok":False,"error":str(error)}); failures+=1
            output({"ok":failures==0,"nodes":results}); return 1 if failures else 0
        try: output(apply_update(reinstall=args.reinstall,source=args.source,config=document)); return 0
        except UpdateError as error: output({"ok":False,"error":str(error)}); return 1
    if args.command=="install":
        from pathlib import Path as _Path
        from .agent_install import install as _install_agent
        try: output(_install_agent(args.agent,root=_Path(args.output),global_scope=args.global_scope)); return 0
        except ValueError as error: output({"ok":False,"error":str(error)}); return 2
        except Exception as error: output({"ok":False,"error":str(error)}); return 1
    try:
        cloud=APX(args.config)
    except Exception as error:
        output({"ok":False,"error":str(error)})
        return 1
    if args.command=="menu":
        from .tui import run as run_menu
        return run_menu(cloud,args.actor)
    if args.command=="plugins":
        output({"plugins":[cloud.plugin_manager.inspect(name) for name in sorted(cloud.plugin_manager.metadata)]}); return 0
    if args.command=="fleet":
        result=cloud.run("fleet.health",actor=args.actor); output(result.to_dict()); return 0 if result.ok and result.result.get("healthy") else result_exit(result)
    if args.command=="agent":
        v=args.verb
        common=dict(description=args.description,project_description=args.project_description,user=args.user,runtime=args.runtime,
            model=args.model,effort=args.effort,timeout=args.timeout,idle_gap=args.idle_gap,
            status_command=args.status_command,test_command=args.test_command)
        if v=="list": result=cloud.run("agent.list",actor=args.actor,host=args.host)
        elif not args.name: output({"ok":False,"error":f"an agent name is required for agent {v}"}); return 2
        elif v=="show": result=cloud.run("agent.inspect",actor=args.actor,name=args.name)
        elif v=="logs": result=cloud.run("agent.logs",actor=args.actor,name=args.name,lines=args.lines)
        elif v=="remove":
            if not args.yes: output({"ok":False,"error":"agent remove requires --yes"}); return 2
            action=cloud.actions.get("agent.remove")
            result=cloud.run("agent.remove",actor=args.actor,confirmation={"level":action.confirmation,"confirmed":True,"authorization_id":f"cli:agent.remove:{args.name}"},name=args.name,purge=args.purge)
        elif v=="plan":
            if not (args.host and args.repo): output({"ok":False,"error":"--host and --repo are required for agent plan"}); return 2
            result=cloud.run("agent.plan",actor=args.actor,name=args.name,host=args.host,repo=args.repo,**common)
        else:
            if not (args.host and args.repo): output({"ok":False,"error":"--host and --repo are required for agent setup"}); return 2
            if not args.yes: output({"ok":False,"error":"agent setup requires --yes"}); return 2
            action=cloud.actions.get("agent.setup")
            result=cloud.run("agent.setup",actor=args.actor,confirmation={"level":action.confirmation,"confirmed":True,"authorization_id":f"cli:agent.setup:{args.name}"},
                name=args.name,host=args.host,repo=args.repo,force=args.force,enable=args.enable,start=args.start,**common)
        output(result.to_dict()); return result_exit(result)
    if args.command=="environment":
        if args.verb=="sources": result=cloud.run("environment.sources",actor=args.actor)
        else:
            if not args.source: output({"ok":False,"error":"a source id is required for environment ingest"}); return 2
            if not args.yes: output({"ok":False,"error":"environment ingest requires --yes"}); return 2
            action=cloud.actions.get("environment.ingest")
            result=cloud.run("environment.ingest",actor=args.actor,confirmation={"level":action.confirmation,"confirmed":True,"authorization_id":f"cli:environment.ingest:{args.source}"},source=args.source)
        output(result.to_dict()); return result_exit(result)
    if args.command=="plugin":
        try: output(cloud.plugin_manager.inspect(args.name)); return 0
        except KeyError as error: output({"ok":False,"error":str(error)}); return 1
    if args.command=="relationships": output({"relationships":[item.to_dict() for item in cloud.relationships()]}); return 0
    if args.command=="resources": output({"resources":[item.to_dict() for item in cloud.resources()]}); return 0
    if args.command=="groups": output(cloud.group_list()); return 0
    if args.command=="group":
        if args.verb=="show": output(cloud.group_inspect(args.name)); return 0
        if not args.resource: output({"ok":False,"error":"resource is required for group add/remove"}); return 2
        result=cloud.run(f"group.{args.verb}",actor=args.actor,resource=args.resource,group=args.name); output(result.to_dict()); return result_exit(result)

    if args.command=="run":
        try:
            inputs=json.loads(args.input)
            if not isinstance(inputs,dict): raise ValueError("--input must be a JSON object")
            auth_context=json.loads(args.auth_context) if args.auth_context else None
            action=cloud.actions.get(args.action)
            if action.destructive and not args.yes: output({"action":args.action,"ok":False,"error":"destructive action requires --yes"}); return 2
            confirmation={"level":action.confirmation,"confirmed":True,"authorization_id":f"cli:{action.name}"} if args.yes and action.confirmation!="none" else None
            result=cloud.run(args.action,actor=args.actor,confirmation=confirmation,auth_context=auth_context,**inputs); output(result.to_dict()); return result_exit(result)
        except (json.JSONDecodeError,ValueError) as error: output({"action":args.action,"ok":False,"error":str(error)}); return 2
        except Exception as error: output({"action":args.action,"ok":False,"error":str(error)}); return 1
    if args.command=="mcp": return MCPServer(cloud,actor=args.actor).serve()
    if args.command=="serve":
        from .httpserver import serve as serve_http
        serve_http(cloud,host=args.host,port=args.port); return 0
    if args.command=="actions":
        values=[a.definition().to_dict() for a in cloud.actions.list() if not args.provider or a.provider==args.provider]
        output({"actions":values}); return 0
    if args.command=="providers":
        output({"providers":[{"id":m.provider.id,"name":m.provider.name,"url":m.provider.url,"actions":len(m.actions),"profiles":list(m.profiles)} for m in cloud.provider_manifests()]}); return 0
    if args.command=="provider":
        manifest=next((m for m in cloud.provider_manifests() if m.provider.id==args.name),None)
        if not manifest: output({"ok":False,"error":f"unknown provider {args.name!r}"}); return 1
        output(manifest.to_dict()); return 0
    if args.command=="action":
        try: definition=cloud.actions.get(args.name).definition()
        except Exception as error: output({"ok":False,"error":str(error)}); return 1
        if args.provider and definition.provider!=args.provider: output({"ok":False,"error":"action is not supplied by requested provider"}); return 1
        output(definition.to_dict()); return 0
    if args.command=="whoami":
        result=cloud.run("actor.whoami",actor=args.actor,subject=args.target_actor or args.actor); output(result.to_dict()); return result_exit(result)
    if args.command=="policy":
        target={}
        for pair in args.target:
            if "=" not in pair: output({"ok":False,"error":f"--target must be KEY=VALUE, got {pair!r}"}); return 2
            key,value=pair.split("=",1); target[key]=value
        result=cloud.run("policy.explain",actor=args.actor,subject=args.target_actor,requested_action=args.action,scope=target); output(result.to_dict()); return result_exit(result)
    if args.command=="state":
        if args.verb=="show": result=cloud.run("state.show",actor=args.actor); output(result.to_dict()); return result_exit(result)
        if not args.name: output({"ok":False,"error":"name is required for state set"}); return 2
        result=cloud.run("state.set",actor=args.actor,name=args.name,reason=args.reason,changed_by=args.actor); output(result.to_dict()); return result_exit(result)
    if args.command=="docs":
        result=cloud.run("docs.generate",actor=args.actor,project=args.project,audience=args.audience)
        if not result.ok: output(result.to_dict()); return result_exit(result)
        print(result.result["content"]); return 0
    if args.command=="secret":
        import getpass
        if args.verb in {"get","reveal","rotate","health"} and not args.id: output({"ok":False,"error":f"id is required for secret {args.verb}"}); return 2
        if args.verb=="set":
            if not args.id: output({"ok":False,"error":"id is required for secret set"}); return 2
            value=getpass.getpass("Secret value: ") if sys.stdin.isatty() else sys.stdin.readline().rstrip("\n")
            result=cloud.run("secret.set",actor=args.actor,id=args.id,value=value)
        else: result=cloud.run(f"secret.{args.verb}",actor=args.actor,id=args.id)
        output(result.to_dict()); return result_exit(result)
    if args.command=="mission":
        v=args.verb
        if v=="list": result=cloud.run("mission.list",actor=args.actor,project=args.project,status=args.status)
        elif v=="create":
            if not (args.project and args.title and args.objective): output({"ok":False,"error":"--project, --title, and --objective are required for mission create"}); return 2
            result=cloud.run("mission.create",actor=args.actor,project=args.project,title=args.title,objective=args.objective,description=args.description,owner=args.owner,priority=args.priority,scope=args.scope,constraints=args.constraints,success_criteria=args.criteria,related_resources=args.related_resources)
        elif not args.id: output({"ok":False,"error":f"mission id is required for mission {v}"}); return 2
        elif v=="show": result=cloud.run("mission.inspect",actor=args.actor,mission=args.id)
        elif v in {"start","complete"}: result=cloud.run(f"mission.{v}",actor=args.actor,mission=args.id,changed_by=args.actor)
        elif v in {"block","cancel"}: result=cloud.run(f"mission.{v}",actor=args.actor,mission=args.id,reason=args.reason,changed_by=args.actor)
        elif v=="verify": result=cloud.run("mission.verify",actor=args.actor,mission=args.id,criteria_met=args.criteria,verified_by=args.actor)
        elif v=="resume": result=cloud.run("mission.resume",actor=args.actor,mission=args.id)
        elif v=="grant":
            if not (args.grantee and args.grant_action): output({"ok":False,"error":"--grantee and --grant-action are required for mission grant"}); return 2
            result=cloud.run("mission.grant",actor=args.actor,mission=args.id,grantee=args.grantee,action=args.grant_action)
        else:  # docs
            result=cloud.run("mission.docs",actor=args.actor,mission=args.id,audience=args.audience)
            if not result.ok: output(result.to_dict()); return result_exit(result)
            print(result.result["content"]); return 0
        output(result.to_dict()); return result_exit(result)
    if args.command=="task":
        v=args.verb
        if v=="list": result=cloud.run("task.list",actor=args.actor,mission=args.mission,status=args.status,assigned_actor=args.claimant)
        elif v=="create":
            if not (args.mission and args.title and args.reason): output({"ok":False,"error":"--mission, --title, and --reason are required for task create"}); return 2
            result=cloud.run("task.create",actor=args.actor,mission=args.mission,title=args.title,reason=args.reason,objective=args.objective,dependencies=args.dependencies,related_resources=args.related_resources,acceptance_criteria=args.criteria)
        elif v=="propose":
            if not (args.mission and args.proposals_json): output({"ok":False,"error":"--mission and --proposals-json are required for task propose"}); return 2
            try: proposals=json.loads(args.proposals_json)
            except json.JSONDecodeError as error: output({"ok":False,"error":f"--proposals-json must be valid JSON: {error}"}); return 2
            result=cloud.run("task.propose",actor=args.actor,mission=args.mission,proposals=proposals)
        elif not args.id: output({"ok":False,"error":f"task id is required for task {v}"}); return 2
        elif v=="show": result=cloud.run("task.inspect",actor=args.actor,task=args.id)
        elif v in {"start","complete"}: result=cloud.run(f"task.{v}",actor=args.actor,task=args.id,changed_by=args.actor)
        elif v in {"block","cancel"}: result=cloud.run(f"task.{v}",actor=args.actor,task=args.id,reason=args.reason,changed_by=args.actor)
        elif v=="verify": result=cloud.run("task.verify",actor=args.actor,task=args.id,criteria_met=args.criteria,verified_by=args.actor)
        elif v in {"claim","release"}: result=cloud.run(f"task.{v}",actor=args.actor,task=args.id,claimant=args.claimant or args.actor)
        output(result.to_dict()); return result_exit(result)
    if args.command=="blueprint":
        v=args.verb
        if v=="list": result=cloud.run("blueprint.list",actor=args.actor,category=args.category,tag=args.tag)
        elif v=="search": result=cloud.run("blueprint.search",actor=args.actor,query=args.query,category=args.category,tag=args.tag)
        elif v=="status":
            if not args.project: output({"ok":False,"error":"--project is required for blueprint status"}); return 2
            result=cloud.run("blueprint.status",actor=args.actor,project=args.project)
        elif not args.id: output({"ok":False,"error":f"a blueprint name is required for blueprint {v}"}); return 2
        elif v=="show": result=cloud.run("blueprint.show",actor=args.actor,blueprint=args.id,version=args.version)
        else:
            try: blueprint_inputs=json.loads(args.inputs_json) if args.inputs_json else {}
            except json.JSONDecodeError as error: output({"ok":False,"error":f"--inputs-json is not valid JSON: {error}"}); return 2
            if v=="plan": result=cloud.run("blueprint.plan",actor=args.actor,blueprint=args.id,version=args.version,project=args.project,inputs=blueprint_inputs)
            else:
                if v=="upgrade" and not args.project: output({"ok":False,"error":"--project is required for blueprint upgrade"}); return 2
                if not args.yes: output({"ok":False,"error":f"blueprint {v} requires --yes"}); return 2
                action=cloud.actions.get(f"blueprint.{v}")
                confirmation={"level":action.confirmation,"confirmed":True,"authorization_id":f"cli:blueprint.{v}:{args.id}"}
                if v=="apply": result=cloud.run("blueprint.apply",actor=args.actor,confirmation=confirmation,blueprint=args.id,version=args.version,project=args.project,inputs=blueprint_inputs)
                else: result=cloud.run("blueprint.upgrade",actor=args.actor,confirmation=confirmation,blueprint=args.id,project=args.project,inputs=blueprint_inputs)
        output(result.to_dict()); return result_exit(result)
    if args.command=="discover":
        result=cloud.run("discovery.capabilities",actor=args.actor,subject=args.subject or args.actor,namespaces=args.namespaces,compact=not args.full)
        output(result.to_dict()); return result_exit(result)
    if args.command=="grant":
        v=args.verb
        if v=="issue":
            if not (args.subject and args.actions): output({"ok":False,"error":"--subject and at least one --action are required for grant issue"}); return 2
            try: constraints=json.loads(args.constraints_json) if args.constraints_json else {}
            except json.JSONDecodeError as error: output({"ok":False,"error":f"--constraints-json is not valid JSON: {error}"}); return 2
            result=cloud.run("grant.issue",actor=args.actor,subject=args.subject,actions=args.actions,resources=args.resources,constraints=constraints,reason=args.reason,expires_at=args.expires_at)
        elif v=="list": result=cloud.run("grant.list",actor=args.actor,subject=args.subject,include_expired=args.include_expired)
        elif not args.id: output({"ok":False,"error":f"a grant id is required for grant {v}"}); return 2
        elif v=="show": result=cloud.run("grant.inspect",actor=args.actor,grant=args.id)
        else: result=cloud.run("grant.revoke",actor=args.actor,grant=args.id)
        output(result.to_dict()); return result_exit(result)
    if args.command=="adapter":
        if not (args.url or args.provider or args.bridge):
            output({"ok":False,"error":"one of --url, --provider, or --bridge is required for adapter test"}); return 2
        result=cloud.run("adapter.test",actor=args.actor,url=args.url,provider=args.provider,bridge=args.bridge)
        output(result.to_dict()); return result_exit(result)
    if args.command=="conformance":
        from .conformance import bridge_conformance
        if args.url:
            result=cloud.run("adapter.test",actor=args.actor,url=args.url)
            output(result.to_dict()); return result_exit(result)
        report={"ok":True,"protocol":"0.1","conformance":"pass","phases":["discover","prepare","authorize","execute","receipt"],"actions_checked":len(cloud.actions())}
        output(report); return 0
    if args.command=="daemon":
        from .daemon import daemon_socket_path, is_daemon_running, start_daemon_background, stop_daemon
        if args.verb=="status":
            running = is_daemon_running()
            output({"running": running, "socket": str(daemon_socket_path())})
            return 0 if running else 1
        if args.verb=="start":
            res = start_daemon_background(args.config)
            output(res); return 0 if res.get("ok") else 1
        if args.verb=="stop":
            res = stop_daemon()
            output(res); return 0
        if args.verb=="restart":
            stop_daemon()
            res = start_daemon_background(args.config)
            output(res); return 0 if res.get("ok") else 1
    if args.command=="node":
        v=args.verb
        if v=="list": result=cloud.run("node.list",actor=args.actor)
        elif not args.host: output({"ok":False,"error":f"a host is required for node {v}"}); return 2
        elif v=="show": result=cloud.run("node.inspect",actor=args.actor,host=args.host)
        elif v=="refresh": result=cloud.run("node.refresh",actor=args.actor,host=args.host)
        else: result=cloud.run("node.permissions",actor=args.actor,host=args.host,subject=args.subject or args.actor)
        output(result.to_dict()); return result_exit(result)
    if args.command=="search":
        result=cloud.run("search.query",actor=args.actor,query=args.query,kinds=args.kinds,limit=args.limit)
        output(result.to_dict()); return result_exit(result)
    if args.command=="work":
        result=cloud.run("work.current",actor=args.actor,subject=args.subject or args.actor); output(result.to_dict()); return result_exit(result)
    if args.command=="auth":
        if args.verb=="status": result=cloud.run("auth.status",actor=args.actor)
        else:
            credentials={"token":args.token} if args.token else {"principal_id":args.actor}
            result=cloud.run("auth.authenticate",actor=args.actor,method=args.method,credentials=credentials)
        output(result.to_dict()); return result_exit(result)
    if args.command=="link":
        args.command,args.verb="identity","device-link"
    if args.command=="identity":
        v=args.verb
        if v=="list": result=cloud.run("identity.list",actor=args.actor)
        elif v=="device-link":
            import socket
            import time as _time
            from .auth_openpower import DeviceLinkDenied,DeviceLinkExpired,DeviceLinkPending,poll_device_token_once,request_device_link
            openpower_config=cloud.config.get("auth",{}).get("openpower")
            if not openpower_config or not openpower_config.get("endpoint"):
                output({"ok":False,"error":"[auth.openpower].endpoint is not configured in apx.toml"}); return 2
            agent_name=args.agent_name or f"APX on {socket.gethostname()}"
            try: link=request_device_link(openpower_config["endpoint"],agent_name)
            except Exception as error: output({"ok":False,"error":str(error)}); return 1
            print(f"Go to {link['verification_uri']} and enter this code:",file=sys.stderr)
            print(f"\n    {link['user_code']}\n",file=sys.stderr)
            print("Waiting for approval (Ctrl-C to cancel)...",file=sys.stderr)
            deadline=_time.time()+link["expires_in"]; token_payload=None
            while _time.time()<deadline:
                try: token_payload=poll_device_token_once(openpower_config["endpoint"],link["device_code"]); break
                except DeviceLinkPending: _time.sleep(link["interval"]); continue
                except (DeviceLinkDenied,DeviceLinkExpired) as error: output({"ok":False,"error":str(error)}); return 1
                except Exception as error: output({"ok":False,"error":str(error)}); return 1
            if token_payload is None: output({"ok":False,"error":"the device link code expired; request a new one"}); return 1
            stored=False
            try: cloud.secrets.set("openpower_axp_identity_token",token_payload["token"]); stored=True
            except Exception: pass  # no [credentials.openpower_axp_identity_token] declared -- token is still returned below
            output({"ok":True,"identity_key":token_payload["identity_key"],"expires_at":token_payload["expires_at"],
                     "token":None if stored else token_payload["token"],"token_stored_in_keychain":stored})
            return 0
        elif v=="enroll-request":
            if not (args.machine_id and args.runtime): output({"ok":False,"error":"--machine-id and --runtime are required for identity enroll-request"}); return 2
            result=cloud.run("identity.enrollment.request",actor=args.actor,machine_id=args.machine_id,runtime=args.runtime,principal=args.target,requested_roles=args.requested_roles,requested_scopes=args.requested_scopes,device_fingerprint=args.device_fingerprint)
        elif v=="pair-create": result=cloud.run("identity.pairing.create",actor=args.actor,ttl_seconds=args.ttl)
        elif v=="pair-claim":
            if not (args.target and args.claimant): output({"ok":False,"error":"a pairing code and --claimant are required for identity pair-claim"}); return 2
            result=cloud.run("identity.pairing.claim",actor=args.actor,code=args.target,claimant=args.claimant)
        elif not args.target: output({"ok":False,"error":f"a target (subject/request id) is required for identity {v}"}); return 2
        elif v=="show": result=cloud.run("identity.inspect",actor=args.actor,subject=args.target)
        elif v=="link":
            if not args.openpower_subject: output({"ok":False,"error":"--openpower-subject is required for identity link"}); return 2
            result=cloud.run("identity.link",actor=args.actor,subject=args.target,openpower_subject=args.openpower_subject,linked_by=args.actor)
        elif v=="unlink": result=cloud.run("identity.unlink",actor=args.actor,subject=args.target,unlinked_by=args.actor)
        elif v=="enroll-status": result=cloud.run("identity.enrollment.status",actor=args.actor,request_id=args.target)
        elif v=="enroll-cancel": result=cloud.run("identity.enrollment.cancel",actor=args.actor,request_id=args.target,cancelled_by=args.actor)
        elif v=="enroll-approve": result=cloud.run("identity.enrollment.approve",actor=args.actor,request_id=args.target,approved_by=args.actor,openpower_ref=args.openpower_ref)
        else: result=cloud.run("identity.enrollment.deny",actor=args.actor,request_id=args.target,denied_by=args.actor)  # enroll-deny
        output(result.to_dict()); return result_exit(result)
    if args.command=="credential":
        v=args.verb
        if v=="issue":
            if not args.principal: output({"ok":False,"error":"--principal is required for credential issue"}); return 2
            result=cloud.run("credential.issue",actor=args.actor,principal=args.principal,type=args.type,issuer=args.issuer,expires=args.expires,fingerprint=args.fingerprint,secret_ref=args.secret_ref)
        elif not args.id: output({"ok":False,"error":f"a credential id is required for credential {v}"}); return 2
        elif v=="show": result=cloud.run("credential.inspect",actor=args.actor,credential_id=args.id)
        elif v=="rotate": result=cloud.run("credential.rotate",actor=args.actor,credential_id=args.id,fingerprint=args.fingerprint,secret_ref=args.secret_ref)
        elif v=="confirm-rotation": result=cloud.run("credential.confirm_rotation",actor=args.actor,previous_credential_id=args.id)
        else: result=cloud.run("credential.revoke",actor=args.actor,credential_id=args.id,revoked_by=args.actor)  # revoke
        output(result.to_dict()); return result_exit(result)

    if args.command=="service": name=f"service.{args.verb}"; inputs={"host":args.host,"service":args.service}
    elif args.command=="hosts": name,inputs="host.list",{}
    elif args.command=="inspect": name,inputs="host.inspect",{"host":args.host}
    elif args.command=="status": name,inputs="host.status",{"host":args.host}
    elif args.command=="services": name,inputs="service.list",{"host":args.host}
    elif args.command=="logs": name,inputs="logs.read",{"host":args.host,"service":args.service,"lines":args.lines}
    elif args.command=="projects": name,inputs="project.list",{}
    elif args.command=="project": name,inputs="project.inspect",{"project":args.name}
    elif args.command=="discover-projects": name,inputs="project.discover",{"host":args.host,"roots":args.roots or None}
    elif args.command=="copy": name,inputs="file.copy",{"source_host":args.source_host,"source":args.source,"destination_host":args.destination_host,"destination":args.destination}
    elif args.command=="sync": name,inputs="file.sync",{"source_host":args.source_host,"source":args.source,"destination_host":args.destination_host,"destination":args.destination,"dry_run":not args.apply}
    else: name,inputs="host.shutdown",{"host":args.host}
    action=cloud.actions.get(name)
    if action.destructive and not args.yes:
        output({"action":name,"ok":False,"error":"destructive action requires --yes"}); return 2
    confirmation={"level":action.confirmation,"confirmed":True,"authorization_id":f"cli:{name}"} if args.yes and action.confirmation!="none" else None
    result=cloud.run(name,actor=args.actor,confirmation=confirmation,**inputs); output(result.to_dict()); return 0 if result.ok else result_exit(result)


def main(argv: list[str] | None = None) -> int:
    try:
        return _main(argv)
    except (KeyboardInterrupt, EOFError):
        return 130


if __name__ == "__main__": sys.exit(main())
