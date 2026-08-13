# SPDX-License-Identifier: MPL-2.0
from .provider import HTTPProviderPlugin, ProviderAction
from ..axp import VersionInfo

class Plugin(HTTPProviderPlugin):
    name="cloudflare"; description="Cloudflare token, zone, DNS, and tunnel discovery."
    base_url="https://api.cloudflare.com/client/v4"
    version_info=VersionInfo(configured="v4",api_family="client",api_version="v4",supported=("v4",),recommended="v4",compatibility="supported",source="official Cloudflare API reference")
    actions=(ProviderAction("cloudflare.status","/user/tokens/verify","result"),ProviderAction("cloudflare.zone.list","/zones","result"),ProviderAction("cloudflare.zone.inspect","/zones/{zone_id}","result",("zone_id",)),ProviderAction("cloudflare.dns.list","/zones/{zone_id}/dns_records","result",("zone_id",)),ProviderAction("cloudflare.tunnel.list","/accounts/{account_id}/tunnels","result",("account_id",)),ProviderAction("cloudflare.tunnel.inspect","/accounts/{account_id}/tunnels/{tunnel_id}","result",("account_id","tunnel_id")),ProviderAction("cloudflare.setting.list","/zones/{zone_id}/settings","result",("zone_id",)),ProviderAction("cloudflare.ruleset.list","/zones/{zone_id}/rulesets","result",("zone_id",)),ProviderAction("cloudflare.access_rule.list","/zones/{zone_id}/firewall/access_rules/rules","result",("zone_id",)),ProviderAction("cloudflare.turnstile.list","/accounts/{account_id}/challenges/widgets","result",("account_id",)),)
