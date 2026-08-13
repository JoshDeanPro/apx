from __future__ import annotations

import json
import subprocess
import threading
from dataclasses import dataclass
from typing import Any

from .base import AdapterMetadata


class MCPAdapterError(RuntimeError): pass


class MCPStdioAdapter:
    """One configured MCP server over stdio. No federation or persistence."""
    metadata=AdapterMetadata("mcp_stdio","0.1","Discover and invoke tools from one MCP stdio server.",( "mcp",))

    def __init__(self, command: list[str], *, timeout: int = 30):
        if not command: raise ValueError("MCP command is required")
        self.command=command; self.timeout=timeout; self.process=None; self._next_id=0

    def _start(self):
        if self.process and self.process.poll() is None: return
        self.process=subprocess.Popen(self.command,stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True,bufsize=1)
        self._request("initialize",{"protocolVersion":"2025-06-18","capabilities":{},"clientInfo":{"name":"apx","version":"0.5.0"}})
        self._notify("notifications/initialized")

    def _request(self,method: str,params: dict[str,Any]):
        if not self.process or not self.process.stdin or not self.process.stdout: raise MCPAdapterError("MCP server is not running")
        self._next_id+=1; ident=self._next_id; result={}
        def exchange():
            try:
                self.process.stdin.write(json.dumps({"jsonrpc":"2.0","id":ident,"method":method,"params":params})+"\n"); self.process.stdin.flush()
                while True:
                    line=self.process.stdout.readline()
                    if not line: result["error"]="MCP server closed the connection"; return
                    message=json.loads(line)
                    if message.get("id")==ident: result["message"]=message; return
            except Exception as error: result["error"]=str(error)
        thread=threading.Thread(target=exchange,daemon=True); thread.start(); thread.join(self.timeout)
        if thread.is_alive(): self.close(); raise MCPAdapterError(f"MCP request timed out after {self.timeout}s")
        if "error" in result: raise MCPAdapterError(result["error"])
        message=result["message"]
        if "error" in message: raise MCPAdapterError(message["error"].get("message","MCP error"))
        return message.get("result",{})

    def _notify(self,method: str):
        if self.process and self.process.stdin: self.process.stdin.write(json.dumps({"jsonrpc":"2.0","method":method})+"\n"); self.process.stdin.flush()

    def tools(self): self._start(); return self._request("tools/list",{}).get("tools",[])
    def call(self,name: str,arguments: dict[str,Any] | None = None): self._start(); return self._request("tools/call",{"name":name,"arguments":arguments or {}})
    def health(self):
        try: return {"ok":True,"adapter":"mcp_stdio","tools":len(self.tools())}
        except Exception as error: return {"ok":False,"adapter":"mcp_stdio","error":str(error)}
    def close(self):
        if self.process:
            process=self.process; process.terminate()
            try: process.wait(timeout=3)
            except subprocess.TimeoutExpired: process.kill(); process.wait(timeout=3)
            for stream in (process.stdin,process.stdout,process.stderr):
                if stream: stream.close()
            self.process=None
