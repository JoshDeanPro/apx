# SPDX-License-Identifier: MPL-2.0
from __future__ import annotations

import shutil
import socket

from ...actions import ActionError, RegisteredAction
from ...plugins import PluginMetadata
from .models import databases_from_config

class Plugin:
    name="databases"
    metadata=PluginMetadata("databases","0.4.0","Configured and host-discovered PostgreSQL/MySQL database resources.",resources=("database",),actions=("database.list","database.discover","database.inspect","database.status","database.version"),optional_dependencies=("psql","pg_dump","pg_restore","mysql","mysqldump"))
    def __init__(self,config=None): self.config=config or {}
    def setup(self,api):
        self.api=api
        def all_databases(): return databases_from_config(api.cloud.config.get("databases",[]),api.cloud.credentials)
        api.discover_resources(lambda:[database.to_resource() for database in all_databases()])
        def listing(): return {"databases":[database.to_resource().to_dict() for database in all_databases()]}
        def discover(host):
            info=api.cloud.core.host_info(host); services=api.cloud.core.service_list(host).get("services",[])
            names=[item.get("name","").lower() for item in services]
            found=[]
            for engine,capability,markers in (("postgres","postgres",("postgresql","postgres")),("mysql","mysql",("mysql","mariadb"))):
                tool=info["capabilities"].get(capability,{})
                matches=sorted({name for name in names if any(marker in name for marker in markers)})
                if tool.get("available") or matches:
                    found.append({"engine":engine,"host":host,"client_available":bool(tool.get("available")),"client_version":tool.get("version"),"services":matches,"configured_endpoints":[item.id for item in all_databases() if item.engine==engine]})
            return {"host":host,"databases":found,"note":"Service/tool discovery does not authenticate or infer passwords."}
        def get(database):
            return next((item for item in all_databases() if item.id==database),None)
        def inspect(database):
            item=get(database)
            if not item: raise ActionError(f"unknown database {database!r}")
            return item.to_resource().to_dict()
        def status(database,timeout=3):
            item=get(database)
            if not item: raise ActionError(f"unknown database {database!r}")
            try:
                with socket.create_connection((item.host,item.port),timeout=max(1,min(timeout,10))): reachable=True
            except OSError: reachable=False
            return {"database":database,"engine":item.engine,"endpoint":item.host,"port":item.port,"reachable":reachable,"authenticated":False}
        def version(database):
            item=get(database)
            if not item: raise ActionError(f"unknown database {database!r}")
            tools=("psql","pg_dump","pg_restore") if item.engine=="postgres" else ("mysql","mysqldump")
            return {"database":database,"engine":item.engine,"configured":item.version,"tools":{tool:{"available":bool(shutil.which(tool))} for tool in tools}}
        empty={"type":"object","properties":{},"additionalProperties":False}; one={"type":"object","properties":{"database":{"type":"string"}},"required":["database"],"additionalProperties":False}
        api.register_action(RegisteredAction("database.list","List database resources",listing,empty))
        api.register_action(RegisteredAction("database.discover","Discover database tools and native services on a host",discover,{"type":"object","properties":{"host":{"type":"string"}},"required":["host"],"additionalProperties":False}))
        api.register_action(RegisteredAction("database.inspect","Inspect a database resource",inspect,one))
        api.register_action(RegisteredAction("database.status","Check database endpoint reachability without authentication",status,{"type":"object","properties":{"database":{"type":"string"},"timeout":{"type":"integer","minimum":1,"maximum":10}},"required":["database"],"additionalProperties":False}))
        api.register_action(RegisteredAction("database.version","Report configured engine version and available client tools",version,one))
