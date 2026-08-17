# SPDX-License-Identifier: MIT
from .provider import HTTPProviderPlugin, ProviderAction
from ..axp import VersionInfo

class Plugin(HTTPProviderPlugin):
    name="porkbun"; description="Porkbun domains, DNS, nameserver, and account discovery."
    base_url="https://api.porkbun.com/api/json/v3"
    version_info=VersionInfo(configured="v3",api_family="domains",api_version="v3",supported=("v3",),recommended="v3",latest_known="v3.9 documentation release",compatibility="current",source="official Porkbun API v3.9 documentation")
    credential_headers=(("api_key","X-API-Key",""),("secret_key","X-Secret-API-Key",""))
    actions=(ProviderAction("porkbun.status","/ping",api_version="v3"),ProviderAction("porkbun.domain.list","/domain/listAll","domains",api_version="v3"),ProviderAction("porkbun.domain.inspect","/domain/get/{domain}",parameters=("domain",),api_version="v3"),ProviderAction("porkbun.dns.list","/dns/retrieve/{domain}","records",("domain",),api_version="v3"))
