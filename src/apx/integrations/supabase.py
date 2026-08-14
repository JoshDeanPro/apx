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
        schema_schema={"type":"object","properties":{"project_ref":{"type":"string"},"schema":{"type":"string"}},"required":["project_ref"],"additionalProperties":False}
        api.register_action(RegisteredAction("supabase.schema.snapshot","Read the current table/column shape of a Supabase project's schema",self._schema_snapshot,schema_schema,True,False))
        api.register_action(RegisteredAction("supabase.schema.watch","Snapshot a Supabase project's schema and report drift (renamed/added/removed tables or columns) since the last watch, regardless of who made the change",self._schema_watch,schema_schema,False,False))

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

    def _query_url(self, project_ref: str) -> str:
        if not project_ref or not all(c.isalnum() or c in "-_" for c in project_ref): raise ValueError("invalid Supabase project ref")
        return f"{self.base_url}/projects/{project_ref}/database/query"

    def _schema_snapshot(self, project_ref: str, schema: str = "public") -> dict[str,Any]:
        if not schema or not all(c.isalnum() or c=="_" for c in schema): raise ValueError("invalid schema name")
        query=f"select table_name, column_name, data_type, is_nullable from information_schema.columns where table_schema = '{schema}' order by table_name, ordinal_position;"
        response=self.http.request("POST",self._query_url(project_ref),headers=self.headers(),body={"query":query},timeout=int(self.config.get("timeout",30)))
        tables: dict[str,list[dict[str,Any]]]={}
        for row in response.body or []:
            tables.setdefault(row["table_name"],[]).append({"column":row["column_name"],"type":row["data_type"],"nullable":row["is_nullable"]=="YES"})
        return {"provider":self.name,"project_ref":project_ref,"schema":schema,"tables":tables}

    def _schema_watch(self, project_ref: str, schema: str = "public") -> dict[str,Any]:
        snapshot=self._schema_snapshot(project_ref,schema)
        result=self.api.cloud.run("drift.check",name=f"supabase.schema:{project_ref}:{schema}",payload=snapshot["tables"])
        if not result.ok: raise RuntimeError(result.error.to_dict() if result.error else "drift.check failed")
        return result.result
