from __future__ import annotations

import argparse
import json
import sys

from .cloud import LocalCloud
from .protocol import MCPServer


def output(value: object) -> None: print(json.dumps(value,indent=2,ensure_ascii=False))


def main(argv: list[str] | None = None) -> int:
    parser=argparse.ArgumentParser(prog="localcloud",description="Use your computers and services together.")
    parser.add_argument("--config",help="TOML configuration path")
    parser.add_argument("--yes",action="store_true",help="confirm destructive actions")
    parser.add_argument("--actor",help="acting identity, e.g. agent::mac (defaults to the configured default_actor)")
    sub=parser.add_subparsers(dest="command",required=True)
    init=sub.add_parser("init",help="discover this machine and create minimal configuration")
    init.add_argument("--output",default="localcloud.toml")
    init.add_argument("--host",action="append",default=[],metavar="NAME=SSH_TARGET")
    init.add_argument("--non-interactive",action="store_true")
    init.add_argument("--force",action="store_true")
    sub.add_parser("doctor",help="diagnose configuration, hosts, plugins, and MCP")
    sub.add_parser("plugins",help="list plugin metadata and health")
    plugin=sub.add_parser("plugin",help="inspect a plugin"); plugin.add_argument("name")
    sub.add_parser("relationships",help="list resource relationships")
    sub.add_parser("resources",help="list AXP resources")
    sub.add_parser("groups",help="list resource groups")
    group=sub.add_parser("group",help="inspect or change a group"); group.add_argument("verb",choices=["show","add","remove"]); group.add_argument("name"); group.add_argument("resource",nargs="?")
    create=sub.add_parser("create",help="scaffold an extension"); create.add_argument("kind",choices=["plugin","action","adapter"]); create.add_argument("name"); create.add_argument("--output",default=".")
    run=sub.add_parser("run",help="run any configured AXP action"); run.add_argument("action"); run.add_argument("--input",default="{}",help="JSON object of action inputs")
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
    sub.add_parser("actions",help="list the shared action catalog")
    openpower=sub.add_parser("openpower",help="report this machine to openpower.one and run its dispatched commands")
    openpower.add_argument("verb",choices=["sync","run"])
    openpower.add_argument("--interval",type=int,default=30,help="seconds between cycles, for 'run' (default 30)")
    openpower.add_argument("--device-name",help="override the reported device name (default: this machine's hostname)")
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
    work=sub.add_parser("work",help="what is this actor currently supposed to be doing"); work.add_argument("verb",choices=["current"]); work.add_argument("subject",nargs="?")
    auth=sub.add_parser("auth",help="authentication provider status / authenticate")
    auth.add_argument("verb",choices=["status","authenticate"]); auth.add_argument("--method",default="local"); auth.add_argument("--token",help="bearer token/JWT, for --method openpower")
    identity=sub.add_parser("identity",help="manage Principals, OpenPower links, enrollment, and device pairing")
    identity.add_argument("verb",choices=["list","show","link","unlink","enroll-request","enroll-status","enroll-cancel","enroll-approve","enroll-deny","pair-create","pair-claim","device-link"])
    identity.add_argument("target",nargs="?",help="subject id / enrollment request id / pairing code, depending on verb")
    identity.add_argument("--openpower-subject"); identity.add_argument("--openpower-ref")
    identity.add_argument("--machine-id"); identity.add_argument("--runtime")
    identity.add_argument("--role",action="append",default=[],dest="requested_roles"); identity.add_argument("--scope",action="append",default=[],dest="requested_scopes")
    identity.add_argument("--device-fingerprint"); identity.add_argument("--claimant"); identity.add_argument("--ttl",type=int,default=600)
    identity.add_argument("--agent-name",help="shown to the human approving this link, for identity device-link (default: 'AXP on <hostname>')")
    credential=sub.add_parser("credential",help="manage ActorCredentials (authenticate the actor -- distinct from provider secrets)")
    credential.add_argument("verb",choices=["issue","show","rotate","confirm-rotation","revoke"])
    credential.add_argument("id",nargs="?")
    credential.add_argument("--principal"); credential.add_argument("--type",default="opaque_bearer"); credential.add_argument("--issuer",default="local")
    credential.add_argument("--expires"); credential.add_argument("--fingerprint"); credential.add_argument("--secret-ref")
    args=parser.parse_args(argv)
    if args.command=="init":
        from .setup import initialize
        try: output(initialize(args.output,ssh_hosts=args.host,interactive=not args.non_interactive,force=args.force)); return 0
        except Exception as error: output({"ok":False,"error":str(error)}); return 1
    if args.command=="doctor":
        from .doctor import diagnose
        result=diagnose(args.config); output(result); return 0 if result["ok"] else 1
    if args.command=="create":
        from .scaffold import create
        try: output(create(args.kind,args.name,args.output)); return 0
        except Exception as error: output({"ok":False,"error":str(error)}); return 1
    cloud=LocalCloud(args.config)
    if args.command=="plugins":
        output({"plugins":[cloud.plugin_manager.inspect(name) for name in sorted(cloud.plugin_manager.metadata)]}); return 0
    if args.command=="plugin":
        try: output(cloud.plugin_manager.inspect(args.name)); return 0
        except KeyError as error: output({"ok":False,"error":str(error)}); return 1
    if args.command=="relationships": output({"relationships":[item.to_dict() for item in cloud.relationships()]}); return 0
    if args.command=="resources": output({"resources":[item.to_dict() for item in cloud.resources()]}); return 0
    if args.command=="groups": output(cloud.group_list()); return 0
    if args.command=="group":
        if args.verb=="show": output(cloud.group_inspect(args.name)); return 0
        if not args.resource: output({"ok":False,"error":"resource is required for group add/remove"}); return 2
        result=cloud.run(f"group.{args.verb}",actor=args.actor,resource=args.resource,group=args.name); output(result.to_dict()); return 0 if result.ok else 1
    if args.command=="run":
        try:
            inputs=json.loads(args.input)
            if not isinstance(inputs,dict): raise ValueError("--input must be a JSON object")
            action=cloud.actions.get(args.action)
            if action.destructive and not args.yes: output({"action":args.action,"ok":False,"error":"destructive action requires --yes"}); return 2
            result=cloud.run(args.action,actor=args.actor,**inputs); output(result.to_dict()); return 0 if result.ok else 1
        except Exception as error: output({"action":args.action,"ok":False,"error":str(error)}); return 1
    if args.command=="mcp": return MCPServer(cloud,actor=args.actor).serve()
    if args.command=="actions":
        output({"actions":[{"name":a.name,"description":a.description,"read_only":a.read_only,"destructive":a.destructive} for a in cloud.actions.list()]}); return 0
    if args.command=="whoami":
        result=cloud.run("actor.whoami",actor=args.actor,subject=args.target_actor or args.actor); output(result.to_dict()); return 0 if result.ok else 1
    if args.command=="policy":
        target={}
        for pair in args.target:
            if "=" not in pair: output({"ok":False,"error":f"--target must be KEY=VALUE, got {pair!r}"}); return 2
            key,value=pair.split("=",1); target[key]=value
        result=cloud.run("policy.explain",actor=args.actor,subject=args.target_actor,requested_action=args.action,scope=target); output(result.to_dict()); return 0 if result.ok else 1
    if args.command=="state":
        if args.verb=="show": result=cloud.run("state.show",actor=args.actor); output(result.to_dict()); return 0 if result.ok else 1
        if not args.name: output({"ok":False,"error":"name is required for state set"}); return 2
        result=cloud.run("state.set",actor=args.actor,name=args.name,reason=args.reason,changed_by=args.actor); output(result.to_dict()); return 0 if result.ok else 1
    if args.command=="docs":
        result=cloud.run("docs.generate",actor=args.actor,project=args.project,audience=args.audience)
        if not result.ok: output(result.to_dict()); return 1
        print(result.result["content"]); return 0
    if args.command=="secret":
        import getpass
        if args.verb in {"get","reveal","rotate","health"} and not args.id: output({"ok":False,"error":f"id is required for secret {args.verb}"}); return 2
        if args.verb=="set":
            if not args.id: output({"ok":False,"error":"id is required for secret set"}); return 2
            value=getpass.getpass("Secret value: ") if sys.stdin.isatty() else sys.stdin.readline().rstrip("\n")
            result=cloud.run("secret.set",actor=args.actor,id=args.id,value=value)
        else: result=cloud.run(f"secret.{args.verb}",actor=args.actor,id=args.id)
        output(result.to_dict()); return 0 if result.ok else 1
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
            if not result.ok: output(result.to_dict()); return 1
            print(result.result["content"]); return 0
        output(result.to_dict()); return 0 if result.ok else 1
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
        output(result.to_dict()); return 0 if result.ok else 1
    if args.command=="work":
        result=cloud.run("work.current",actor=args.actor,subject=args.subject or args.actor); output(result.to_dict()); return 0 if result.ok else 1
    if args.command=="auth":
        if args.verb=="status": result=cloud.run("auth.status",actor=args.actor)
        else:
            credentials={"token":args.token} if args.token else {"principal_id":args.actor}
            result=cloud.run("auth.authenticate",actor=args.actor,method=args.method,credentials=credentials)
        output(result.to_dict()); return 0 if result.ok else 1
    if args.command=="identity":
        v=args.verb
        if v=="list": result=cloud.run("identity.list",actor=args.actor)
        elif v=="device-link":
            import socket
            import time as _time
            from .auth_openpower import DeviceLinkDenied,DeviceLinkExpired,DeviceLinkPending,poll_device_token_once,request_device_link
            openpower_config=cloud.config.get("auth",{}).get("openpower")
            if not openpower_config or not openpower_config.get("endpoint"):
                output({"ok":False,"error":"[auth.openpower].endpoint is not configured in localcloud.toml"}); return 2
            agent_name=args.agent_name or f"AXP on {socket.gethostname()}"
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
        output(result.to_dict()); return 0 if result.ok else 1
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
        output(result.to_dict()); return 0 if result.ok else 1
    if args.command=="openpower":
        from . import openpower_bridge
        openpower_config=cloud.config.get("auth",{}).get("openpower")
        if not openpower_config or not openpower_config.get("endpoint"):
            output({"ok":False,"error":"[auth.openpower].endpoint is not configured in localcloud.toml"}); return 2
        try: token=cloud.secrets.reveal("openpower_axp_identity_token")["value"]
        except Exception as error:
            output({"ok":False,"error":f"no OpenPower identity token available -- run 'localcloud identity device-link' first: {error}"}); return 2
        if not token:
            output({"ok":False,"error":"no OpenPower identity token available -- run 'localcloud identity device-link' first"}); return 2
        actor=args.actor or cloud.actors.resolve_default()
        if args.verb=="sync":
            try: result=openpower_bridge.run_once(cloud,openpower_config["endpoint"],token,actor=actor)
            except Exception as error: output({"ok":False,"error":str(error)}); return 1
            output({"ok":True,**result}); return 0
        # run: loop forever, printing progress to stderr; Ctrl-C to stop.
        def _on_tick(result):
            print(f"[openpower] device={result.get('device_id')} commands_executed={len(result.get('commands_executed',[]))}",file=sys.stderr)
        try:
            openpower_bridge.run_loop(cloud,openpower_config["endpoint"],token,actor=actor,interval=args.interval,on_tick=_on_tick)
        except KeyboardInterrupt:
            output({"ok":True,"stopped":True}); return 0
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
    result=cloud.run(name,**inputs); output(result.to_dict()); return 0 if result.ok else 1


if __name__ == "__main__": sys.exit(main())
