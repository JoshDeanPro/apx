# SPDX-License-Identifier: MIT
from .models import DatabaseResource

def from_project(project: dict, *, groups=(), tags=()) -> DatabaseResource:
    ref=project["ref"]
    return DatabaseResource(ref,"postgres",f"db.{ref}.supabase.co",5432,"postgres","postgres",project.get("credential"),"require","supabase",project.get("database_version"),project.get("project"),tuple(groups),tuple(tags),{"region":project.get("region"),"project_name":project.get("name")})
