# SPDX-License-Identifier: MIT
from __future__ import annotations

import json
import shutil

from ..actions import ActionError, RegisteredAction
from ..axp import Resource, VersionInfo
from ..plugins import PluginMetadata
from .databases.aws import from_db_instance
from ..process import ProcessError,ProcessTimeout,run

class Plugin:
    name="aws"
    version_info=VersionInfo(api_family="RDS",api_version="2014-10-31",supported=("2014-10-31",),compatibility="supported",source="official AWS RDS API reference")
    metadata=PluginMetadata("aws","0.4.0","AWS RDS endpoint discovery through an existing AWS CLI credential chain.",resources=("provider:aws","database"),actions=("aws.database.list",),optional_dependencies=("awscli",),version_info=version_info,configuration=("enabled","optional profile","optional region"))
    def __init__(self,config=None): self.config=config or {}
    def setup(self,api):
        api.add_resource(Resource("provider:aws","provider","aws",{"configured":True,"connection":"aws_cli"},("aws.database.list",),tuple(self.config.get("groups",())),tuple(self.config.get("tags",())),self.version_info))
        def listing():
            if not shutil.which("aws"): raise ActionError("aws.database.list requires the optional AWS CLI")
            command=["aws"]
            if self.config.get("profile"): command.extend(["--profile",self.config["profile"]])
            if self.config.get("region"): command.extend(["--region",self.config["region"]])
            command.extend(["rds","describe-db-instances","--output","json","--no-cli-pager"])
            try: result=run(command,timeout=30)
            except (ProcessError,ProcessTimeout) as error: raise ActionError(str(error)) from error
            if not result.ok: raise ActionError("AWS RDS discovery failed")
            databases=[from_db_instance(value,groups=self.config.get("groups",()),tags=self.config.get("tags",())).to_resource().to_dict() for value in json.loads(result.stdout).get("DBInstances",[])]
            return {"provider":"aws","api_family":"RDS","api_version":"2014-10-31","databases":databases}
        api.register_action(RegisteredAction("aws.database.list","List AWS RDS/Aurora database endpoints",listing,{"type":"object","properties":{},"additionalProperties":False}))
