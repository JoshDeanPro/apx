from .provider import HTTPProviderPlugin, ProviderAction
from ..axp import VersionInfo

class Plugin(HTTPProviderPlugin):
    name="supabase"; description="Supabase Management API project discovery; databases remain PostgreSQL resources."
    base_url="https://api.supabase.com/v1"
    version_info=VersionInfo(configured="v1",api_family="Management API",api_version="v1",supported=("v1",),recommended="v1",compatibility="supported",source="official Supabase Management API reference")
    actions=(ProviderAction("supabase.status","/projects",api_version="v1"),ProviderAction("supabase.project.list","/projects",api_version="v1"),ProviderAction("supabase.project.inspect","/projects/{project_ref}",parameters=("project_ref",),api_version="v1"))
