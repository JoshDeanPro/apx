# SPDX-License-Identifier: MIT
from .provider import HTTPProviderPlugin, ProviderAction
from ..axp import VersionInfo

class Plugin(HTTPProviderPlugin):
    name="godaddy"; description="GoDaddy multi-generation Domains API discovery."
    base_url="https://api.godaddy.com"
    version_info=VersionInfo(configured="v1,v2,v3",api_family="domains",api_version="multiple",supported=("v1","v2","v3"),recommended="v3 where available",compatibility="supported",source="official GoDaddy Domains REST reference",notes=("v1 account and DNS operations","v2 async operations","v3 discovery and registration"))
    actions=(ProviderAction("godaddy.status","/v1/domains?limit=1",api_version="v1"),ProviderAction("godaddy.domain.list","/v1/domains",api_version="v1"),ProviderAction("godaddy.domain.inspect","/v1/domains/{domain}",parameters=("domain",),api_version="v1"),ProviderAction("godaddy.dns.list","/v1/domains/{domain}/records",parameters=("domain",),api_version="v1"))
