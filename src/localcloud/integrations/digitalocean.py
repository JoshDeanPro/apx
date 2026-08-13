from .provider import HTTPProviderPlugin, ProviderAction
from ..axp import VersionInfo

class Plugin(HTTPProviderPlugin):
    name="digitalocean"; description="DigitalOcean account, Droplet, and managed database discovery."
    base_url="https://api.digitalocean.com/v2"
    version_info=VersionInfo(configured="v2",api_family="REST",api_version="v2",supported=("v2",),recommended="v2",compatibility="supported",source="official DigitalOcean API reference")
    actions=(ProviderAction("digitalocean.status","/account",api_version="v2"),ProviderAction("digitalocean.droplet.list","/droplets","droplets",api_version="v2"),ProviderAction("digitalocean.database.list","/databases","databases",api_version="v2"))
