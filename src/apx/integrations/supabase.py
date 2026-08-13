# SPDX-License-Identifier: MPL-2.0
from typing import Any
from .provider import HTTPProviderPlugin, ProviderAction
from ..actions import RegisteredAction
from ..axp import VersionInfo

class Plugin(HTTPProviderPlugin):
    name="supabase"; description="Supabase Management API project discovery; databases remain PostgreSQL resources."
    base_url="https://api.supabase.com/v1"
    version_info=VersionInfo(configured="v1",api_family="Management API",api_version="v1",supported=("v1",),recommended="v1",compatibility="supported",source="official Supabase Management API reference")
    actions=(ProviderAction("supabase.status","/projects",api_version="v1"),ProviderAction("supabase.project.list","/projects",api_version="v1"),ProviderAction("supabase.project.inspect","/projects/{project_ref}",parameters=("project_ref",),api_version="v1"))

    def setup(self, api):
        super().setup(api)
        project_schema={"type":"object","properties":{"project_ref":{"type":"string"}},"required":["project_ref"],"additionalProperties":False}
        update_schema={"type":"object","properties":{"project_ref":{"type":"string"},"settings":{"type":"object"}},"required":["project_ref","settings"],"additionalProperties":False}
        api.register_action(RegisteredAction("supabase.auth.config.inspect","Read Supabase Auth project configuration",self._auth_inspect,project_schema,True,False))
        api.register_action(RegisteredAction("supabase.auth.config.update","Update an explicit subset of Supabase Auth project configuration",self._auth_update,update_schema,False,False))

    def _auth_url(self, project_ref: str) -> str:
        if not project_ref or not all(c.isalnum() or c in "-_" for c in project_ref): raise ValueError("invalid Supabase project ref")
        return f"{self.base_url}/projects/{project_ref}/config/auth"

    def _auth_inspect(self, project_ref: str) -> dict[str,Any]:
        response=self.http.request("GET",self._auth_url(project_ref),headers=self.headers(),timeout=int(self.config.get("timeout",20)))
        return {"provider":self.name,"project_ref":project_ref,"data":response.body}

    def _auth_update(self, project_ref: str, settings: dict[str,Any]) -> dict[str,Any]:
        allowed={"site_url","uri_allow_list","oauth_server_enabled","oauth_server_authorization_path","oauth_server_allow_dynamic_registration","passkey_enabled","webauthn_rp_display_name","webauthn_rp_id","webauthn_rp_origins",
                 "smtp_host","smtp_port","smtp_user","smtp_pass","smtp_sender_name","smtp_admin_email","smtp_max_frequency","rate_limit_email_sent","mailer_autoconfirm"}
        unknown=set(settings)-allowed
        if unknown: raise ValueError(f"unsupported Supabase Auth settings: {sorted(unknown)}")
        self.http.request("PATCH",self._auth_url(project_ref),headers=self.headers(),body=settings,timeout=int(self.config.get("timeout",20)))
        return self._auth_inspect(project_ref)
