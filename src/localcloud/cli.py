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
    sub=parser.add_subparsers(dest="command",required=True)
    init=sub.add_parser("init",help="discover this machine and create minimal configuration")
    init.add_argument("--output",default="localcloud.toml")
    init.add_argument("--host",action="append",default=[],metavar="NAME=SSH_TARGET")
    init.add_argument("--non-interactive",action="store_true")
    init.add_argument("--force",action="store_true")
    sub.add_parser("doctor",help="diagnose configuration, hosts, plugins, and MCP")
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
    sub.add_parser("mcp",help="serve MCP over stdio")
    args=parser.parse_args(argv)
    if args.command=="init":
        from .setup import initialize
        try: output(initialize(args.output,ssh_hosts=args.host,interactive=not args.non_interactive,force=args.force)); return 0
        except Exception as error: output({"ok":False,"error":str(error)}); return 1
    if args.command=="doctor":
        from .doctor import diagnose
        result=diagnose(args.config); output(result); return 0 if result["ok"] else 1
    cloud=LocalCloud(args.config)
    if args.command=="mcp": return MCPServer(cloud).serve()
    if args.command=="actions":
        output({"actions":[{"name":a.name,"description":a.description,"read_only":a.read_only,"destructive":a.destructive} for a in cloud.actions.list()]}); return 0
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
