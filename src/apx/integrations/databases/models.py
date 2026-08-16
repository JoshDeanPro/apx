# SPDX-License-Identifier: MPL-2.0
from __future__ import annotations

import urllib.parse
from dataclasses import asdict, dataclass, field
from typing import Any

from ...axp import Resource, VersionInfo

DEFAULT_PORTS={"postgres":5432,"postgresql":5432,"mysql":3306,"mariadb":3306}

@dataclass(frozen=True)
class DatabaseResource:
    id: str
    engine: str
    host: str
    port: int
    database: str | None = None
    username: str | None = None
    credential: str | None = None
    tls_mode: str | None = None
    provider: str | None = None
    version: str | None = None
    project: str | None = None
    groups: tuple[str,...] = ()
    tags: tuple[str,...] = ()
    metadata: dict[str,Any] = field(default_factory=dict)

    def to_resource(self) -> Resource:
        # Arbitrary provider metadata stays internal unless a plugin explicitly
        # promotes a safe field; this prevents accidental config-secret output.
        attributes={key:value for key,value in asdict(self).items() if key not in {"id","groups","tags","version","metadata"} and value is not None}
        return Resource(f"database:{self.id}","database",self.id,attributes,("database.inspect","database.status","database.version"),self.groups,self.tags,VersionInfo(detected=self.version,installed=self.version,compatibility="unknown",source="configuration or provider discovery"))


def infer_provider(host: str) -> str | None:
    if host.endswith(".supabase.co"): return "supabase"
    if host.endswith(".rds.amazonaws.com"): return "aws"
    if host.endswith(".db.ondigitalocean.com"): return "digitalocean"
    return None


def parse_database_url(value: str, *, id: str = "database", credential: str | None = None, groups=(), tags=(), project=None) -> DatabaseResource:
    parsed=urllib.parse.urlsplit(value)
    engine={"postgresql":"postgres","postgres":"postgres","mysql":"mysql","mariadb":"mysql"}.get(parsed.scheme)
    if not engine or not parsed.hostname: raise ValueError("unsupported or incomplete database URL")
    query=urllib.parse.parse_qs(parsed.query)
    return DatabaseResource(id,engine,parsed.hostname,parsed.port or DEFAULT_PORTS[parsed.scheme],parsed.path.lstrip("/") or None,urllib.parse.unquote(parsed.username) if parsed.username else None,credential,(query.get("sslmode") or query.get("ssl-mode") or [None])[0],infer_provider(parsed.hostname),None,project,tuple(groups),tuple(tags))


def redact_database_url(value: str) -> str:
    parsed=urllib.parse.urlsplit(value)
    user=urllib.parse.unquote(parsed.username) if parsed.username else None
    auth=(f"{user}:***@" if parsed.password is not None else f"{user}@" if user else "")
    host=parsed.hostname or ""; port=f":{parsed.port}" if parsed.port else ""
    query=urllib.parse.parse_qsl(parsed.query,keep_blank_values=True)
    safe_query=urllib.parse.urlencode([(key,"***" if any(marker in key.lower() for marker in ("password","passwd","secret","token")) else item) for key,item in query])
    return urllib.parse.urlunsplit((parsed.scheme,f"{auth}{host}{port}",parsed.path,safe_query,""))


def databases_from_config(values: list[dict[str,Any]],credentials) -> list[DatabaseResource]:
    databases=[]
    for item in values:
        if item.get("url_credential"):
            try:
                value=credentials.resolve(item["url_credential"])
                databases.append(parse_database_url(value,id=item["id"],credential=item["url_credential"],groups=item.get("groups",()),tags=item.get("tags",()),project=item.get("project")))
            except Exception: pass
        else:
            try:
                engine=item.get("engine","").lower()
                databases.append(DatabaseResource(item["id"],engine,item["host"],int(item.get("port",DEFAULT_PORTS.get(engine,0))),item.get("database"),item.get("username"),item.get("credential"),item.get("tls_mode"),item.get("provider"),item.get("version"),item.get("project"),tuple(item.get("groups",())),tuple(item.get("tags",())),item.get("metadata",{})))
            except Exception: pass
    return databases

