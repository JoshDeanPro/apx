# SPDX-License-Identifier: MIT
"""Small HTTP provider plugin primitives; provider behavior stays outside Core."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from urllib.parse import quote

from ..actions import RegisteredAction
from ..adapters.http import HTTPAdapter
from ..axp import Resource, VersionInfo
from ..plugins import PluginAPI, PluginMetadata


@dataclass(frozen=True)
class ProviderAction:
    name: str
    path: str
    result_key: str | None = None
    parameters: tuple[str,...] = ()
    api_family: str | None = None
    api_version: str | None = None


class HTTPProviderPlugin:
    name="provider"
    base_url=""
    version_info=VersionInfo()
    actions: tuple[ProviderAction,...]=()
    credential_headers: tuple[tuple[str,str,str],...]=(("credential","Authorization","Bearer "),)
    description="HTTP provider integration"

    def __init__(self, config: dict[str,Any] | None = None): self.config=config or {}

    @property
    def metadata(self) -> PluginMetadata:
        credentials=tuple(self.config.get(key,key) for key,_,_ in self.credential_headers)
        return PluginMetadata(self.name,"0.4.0",self.description,resources=(f"provider:{self.name}",),actions=tuple(action.name for action in self.actions),credentials=credentials,version_info=self.version_info,configuration=("enabled","credential references","optional groups/tags"))

    def setup(self, api: PluginAPI) -> None:
        self.api=api; self.http=HTTPAdapter(api.cloud.credentials)
        action_versions={action.name:{"api_family":action.api_family or self.version_info.api_family,"api_version":action.api_version or self.version_info.api_version} for action in self.actions}
        api.add_resource(Resource(f"provider:{self.name}","provider",self.name,{"configured":True,"action_versions":action_versions},tuple(action.name for action in self.actions),tuple(self.config.get("groups",())),tuple(self.config.get("tags",())),self.version_info))
        for action in self.actions: api.register_action(self._registered(action))

    def headers(self) -> dict[str,str]:
        return {header:prefix+self.api.credential(self.config.get(key,key)) for key,header,prefix in self.credential_headers}

    def _registered(self, action: ProviderAction) -> RegisteredAction:
        properties={name:{"type":"string"} for name in action.parameters}
        schema={"type":"object","properties":properties,"required":list(action.parameters),"additionalProperties":False}
        def invoke(_action=action,**values):
            safe_values={key:quote(str(value),safe="") for key,value in values.items()}
            path=_action.path.format(**safe_values)
            response=self.http.request("GET",self.base_url+path,headers=self.headers(),timeout=int(self.config.get("timeout",20)))
            body=response.body
            result=body.get(_action.result_key,[]) if _action.result_key and isinstance(body,dict) else body
            detected=next((value for key,value in response.headers.items() if key.lower() in {"x-api-version","openai-version"}),None)
            return {"provider":self.name,"action":_action.name,"api_family":_action.api_family or self.version_info.api_family,"api_version":_action.api_version or self.version_info.api_version,"detected_api_version":detected,"data":result}
        return RegisteredAction(action.name,f"Read {self.name} {action.name}",invoke,schema,True,False)
