from .provider import HTTPProviderPlugin, ProviderAction
from ..axp import VersionInfo

class Plugin(HTTPProviderPlugin):
    name="openai"; description="OpenAI API identity and model catalog discovery without model invocation."
    base_url="https://api.openai.com/v1"
    version_info=VersionInfo(configured="v1",api_family="REST",api_version="v1",detected="2020-10-01 response header when available",supported=("v1",),recommended="v1",compatibility="supported",source="official OpenAI API reference")
    actions=(ProviderAction("openai.status","/models",api_version="v1"),ProviderAction("openai.models.list","/models","data",api_version="v1"))
