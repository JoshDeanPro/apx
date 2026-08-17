# SPDX-License-Identifier: MIT
from .models import DatabaseResource

def from_cluster(cluster: dict, *, groups=(), tags=()) -> DatabaseResource:
    connection=cluster.get("connection",{}); engine={"pg":"postgres","advanced_pg":"postgres","advanced_mysql":"mysql"}.get(cluster.get("engine"),cluster.get("engine","unknown"))
    return DatabaseResource(cluster.get("id",cluster.get("name","digitalocean-database")),engine,connection.get("host",""),int(connection.get("port",0)),connection.get("database"),connection.get("user"),None,"require" if connection.get("ssl") else None,"digitalocean",cluster.get("version"),None,tuple(groups),tuple(tags),{"name":cluster.get("name"),"region":cluster.get("region"),"status":cluster.get("status")})
