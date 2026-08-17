# SPDX-License-Identifier: MIT
from __future__ import annotations

import json
import re
import sys
import traceback
from typing import Any

from .axp import ActionRequest, Event
from .cloud import APX
from .providers import ActionProvider
from .runtime import ProviderSession

FALLBACK_VERSION = "2025-06-18"


def tool_name(action: str) -> str:
    return "host_info" if action=="host.inspect" else action.replace(".", "_")


class MCPServer:
    def __init__(self, cloud: APX, actor: str | None = None, auth_context: dict[str, Any] | None = None):
        self.cloud = cloud
        self.actor = actor or cloud.actors.resolve_default()
        self.auth_context = auth_context
        self.by_tool = {tool_name(action.name): action for action in cloud.actions.list()}
        self.provider_sessions={provider_id:ProviderSession(provider) for provider_id,provider in cloud.providers.items() if isinstance(provider,ActionProvider)}
        self.cloud.emit(Event("agent.connected","mcp",{"actor":self.actor},{"authenticated":auth_context is not None}))

    def tools(self) -> list[dict[str, Any]]:
        # Same predicate APX.discover()/capability_graph(actor=...) use, so an agent's
        # tool list and a human's UI capability list never diverge -- including Mission
        # and Grant-delegated authority, not just static roles.
        tools=[]
        for name,action in self.by_tool.items():
            if not self.cloud._actor_can_discover(self.actor,action.name): continue
            schema={**action.schema,"properties":dict(action.schema.get("properties",{}))}
            if action.destructive:
                schema["properties"]["confirm"]={"type":"boolean","description":"Must be true for destructive actions."}
                schema["required"]=[*schema.get("required",[]),"confirm"]
            if action.provider and (not action.read_only or action.confirmation!="none"):
                schema["properties"].update({
                    "prepared_action_id":{"type":"string","description":"ID returned by the first, prepare-only call."},
                    "idempotency_key":{"type":"string","description":"Stable key for this logical consequential request."},
                    "authoritative_state_version":{"type":["string","null"]},
                    "confirmation":{"type":"object","description":"Confirmation bound to prepared_action_id."},
                })
            tools.append({"name":name,"title":action.name,"description":action.description,"inputSchema":schema,"annotations":{"readOnlyHint":action.read_only,"destructiveHint":action.destructive,"idempotentHint":action._idempotent(),"openWorldHint":action.provenance not in {"native_apx","local_native"}}})
        return tools

    def dispatch(self, message: dict[str, Any]) -> dict[str, Any] | None:
        if "id" not in message: return None
        ident=message["id"]
        try:
            method=message.get("method"); params=message.get("params") or {}
            if method=="initialize":
                requested=params.get("protocolVersion")
                version=requested if isinstance(requested,str) and re.fullmatch(r"\d{4}-\d{2}-\d{2}",requested) else FALLBACK_VERSION
                from . import __version__
                result={"protocolVersion":version,"capabilities":{"tools":{"listChanged":False}},"serverInfo":{"name":"apx","version":__version__},"instructions":"Use the same discovered APX actions available to human CLI and Python callers. Prefer read-only inspection before mutations."}
            elif method=="ping": result={}
            elif method=="tools/list": result={"tools":self.tools()}
            elif method=="tools/call":
                action=self.by_tool.get(params.get("name"))
                if not action: raise ValueError(f"unknown tool {params.get('name')!r}")
                arguments=dict(params.get("arguments") or {})
                confirmed=arguments.pop("confirm",False)
                if action.destructive and confirmed is not True:
                    raise ValueError("destructive action requires confirm=true")
                session=self.provider_sessions.get(action.provider or "")
                if session and (not action.read_only or action.confirmation!="none"):
                    prepared_id=arguments.pop("prepared_action_id",None); idempotency_key=arguments.pop("idempotency_key",None)
                    state_version=arguments.pop("authoritative_state_version",None); confirmation=arguments.pop("confirmation",None)
                    if not prepared_id:
                        prepared=session.prepare(ActionRequest(action.name,input=arguments,actor=self.actor,auth_context=self.auth_context))
                        outcome=prepared.to_dict()
                    else:
                        if confirmation:
                            authorized=session.authorize(prepared_id,{**confirmation,"prepared_action_id":prepared_id})
                            if not authorized.ok: outcome=authorized.to_dict()
                            else:
                                outcome=session.execute(ActionRequest(action.name,input=arguments,actor=self.actor,auth_context=self.auth_context,
                                    prepared_action_id=prepared_id,idempotency_key=idempotency_key,authoritative_state_version=state_version)).to_dict()
                        else:
                            outcome=session.execute(ActionRequest(action.name,input=arguments,actor=self.actor,auth_context=self.auth_context,
                                prepared_action_id=prepared_id,idempotency_key=idempotency_key,authoritative_state_version=state_version)).to_dict()
                else:
                    confirmation={"level":action.confirmation,"confirmed":True,"authorization_id":f"mcp:{ident}:{action.name}"} if confirmed and action.confirmation!="none" else None
                    outcome=self.cloud.run(action.name,actor=self.actor,auth_context=self.auth_context,confirmation=confirmation,**arguments).compact()
                is_error=outcome.get("ok") is False
                result={"content":[{"type":"text","text":json.dumps(outcome,indent=2)}],"structuredContent":outcome,"isError":is_error}
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
