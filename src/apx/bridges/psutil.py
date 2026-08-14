# SPDX-License-Identifier: MPL-2.0
"""Optional psutil machine-inspection bridge; never an APX Core dependency."""
from __future__ import annotations

from typing import Any

from ..actions import ActionRegistry, RegisteredAction
from ..axp import Capability, Resource
from ..health import ComponentHealth


class PsutilBridge:
    id="psutil"; version="0.1.0"; provenance="standard_bridge"
    def __init__(self,module=None):
        if module is None:
            try: import psutil as module
            except ImportError: module=None
        self.module=module
    def discover_resources(self): return (Resource("machine:local","machine","Local machine",{},capabilities=("machine.inspect",)),)
    def discover_capabilities(self):
        return (Capability("machine.inspect","machine:local","Bounded process, disk, and listener inspection",actions=("machine.disk.usage","machine.process.list","machine.port.list"),provenance=self.provenance,source=self.id,health="healthy" if self.module else "unavailable"),)
    def _required(self):
        if self.module is None: raise RuntimeError("psutil is not installed; enable the optional machine-inspection capability")
        return self.module
    def disk_usage(self,path="/"):
        value=self._required().disk_usage(path)
        return {"path":path,"total":value.total,"used":value.used,"free":value.free,"percent":value.percent,"summary":f"{value.percent}% used"}
    def processes(self,limit=50):
        rows=[]
        for process in self._required().process_iter(("pid","name","username","status")):
            try: rows.append(dict(process.info))
            except Exception: continue
            if len(rows)>=max(1,min(limit,200)): break
        return {"processes":rows,"count":len(rows),"truncated":len(rows)>=limit}
    def ports(self,port=None,limit=100):
        rows=[]
        for item in self._required().net_connections(kind="inet"):
            local=getattr(item,"laddr",None)
            local_port=getattr(local,"port",None)
            if local_port is None and local:
                local_port=local[1]
            if port is not None and local_port!=port: continue
            address=getattr(local,"ip",None)
            if address is None and local:
                address=local[0]
            rows.append({"pid":item.pid,"status":item.status,"address":address,"port":local_port})
            if len(rows)>=max(1,min(limit,500)): break
        return {"listeners":rows,"count":len(rows),"filter":{"port":port} if port is not None else {}}
    def register_actions(self,registry: ActionRegistry):
        obj=lambda p: {"type":"object","properties":p,"additionalProperties":False}
        registry.register(RegisteredAction("machine.disk.usage","Read normalized local disk usage",self.disk_usage,obj({"path":{"type":"string"}}),resource_type="machine",provenance=self.provenance,provider=self.id))
        registry.register(RegisteredAction("machine.process.list","List a bounded set of local processes",self.processes,obj({"limit":{"type":"integer","minimum":1,"maximum":200}}),resource_type="machine",provenance=self.provenance,provider=self.id))
        registry.register(RegisteredAction("machine.port.list","List a bounded set of local network listeners",self.ports,obj({"port":{"type":"integer","minimum":1,"maximum":65535},"limit":{"type":"integer","minimum":1,"maximum":500}}),resource_type="machine",provenance=self.provenance,provider=self.id))
    def health(self): return ComponentHealth(self.id,"healthy" if self.module else "unavailable","optional cross-platform machine inspection",("machine.inspect",))
