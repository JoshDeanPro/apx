from __future__ import annotations

import json
import re
import sys
import traceback
from typing import Any

from .axp import Event
from .cloud import LocalCloud

FALLBACK_VERSION = "2025-06-18"


def tool_name(action: str) -> str:
    return "host_info" if action=="host.inspect" else action.replace(".", "_")


class MCPServer:
    def __init__(self, cloud: LocalCloud, actor: str | None = None, auth_context: dict[str, Any] | None = None):
        self.cloud = cloud
        self.actor = actor or cloud.actors.resolve_default()
        self.auth_context = auth_context
        self.by_tool = {tool_name(action.name): action for action in cloud.actions.list()}
        self.cloud.emit(Event("agent.connected","mcp",{"actor":self.actor},{"authenticated":auth_context is not None}))

    def tools(self) -> list[dict[str, Any]]:
        tools=[]
        for name,action in self.by_tool.items():
            if not self.cloud.policy.might_allow(self.actor,action.name): continue
            schema={**action.schema,"properties":dict(action.schema.get("properties",{}))}
            if action.destructive:
                schema["properties"]["confirm"]={"type":"boolean","description":"Must be true for destructive actions."}
                schema["required"]=[*schema.get("required",[]),"confirm"]
            tools.append({"name":name,"title":action.name,"description":action.description,"inputSchema":schema,"annotations":{"readOnlyHint":action.read_only,"destructiveHint":action.destructive,"idempotentHint":False,"openWorldHint":True}})
        return tools

    def dispatch(self, message: dict[str, Any]) -> dict[str, Any] | None:
        if "id" not in message: return None
        ident=message["id"]
        try:
            method=message.get("method"); params=message.get("params") or {}
            if method=="initialize":
                requested=params.get("protocolVersion")
                version=requested if isinstance(requested,str) and re.fullmatch(r"\d{4}-\d{2}-\d{2}",requested) else FALLBACK_VERSION
                result={"protocolVersion":version,"capabilities":{"tools":{"listChanged":False}},"serverInfo":{"name":"localcloud","version":"0.4.0"},"instructions":"Use the same discovered LOCALCLOUD actions available to human CLI and Python callers. Prefer read-only inspection before mutations."}
            elif method=="ping": result={}
            elif method=="tools/list": result={"tools":self.tools()}
            elif method=="tools/call":
                action=self.by_tool.get(params.get("name"))
                if not action: raise ValueError(f"unknown tool {params.get('name')!r}")
                arguments=dict(params.get("arguments") or {})
                if action.destructive and arguments.pop("confirm",False) is not True:
                    raise ValueError("destructive action requires confirm=true")
                outcome=self.cloud.run(action.name,actor=self.actor,auth_context=self.auth_context,**arguments).to_dict()
                result={"content":[{"type":"text","text":json.dumps(outcome,indent=2)}],"structuredContent":outcome,"isError":not outcome["ok"]}
            else: return {"jsonrpc":"2.0","id":ident,"error":{"code":-32601,"message":f"Method not found: {method}"}}
            return {"jsonrpc":"2.0","id":ident,"result":result}
        except Exception as error:
            return {"jsonrpc":"2.0","id":ident,"error":{"code":-32602,"message":str(error)}}

    def serve(self) -> int:
        for line in sys.stdin:
            try:
                response=self.dispatch(json.loads(line))
                if response is not None: print(json.dumps(response),flush=True)
            except Exception:
                traceback.print_exc(file=sys.stderr)
        return 0
