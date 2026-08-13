# SPDX-License-Identifier: MPL-2.0
from .provider import HTTPProviderPlugin, ProviderAction
from ..axp import VersionInfo

class Plugin(HTTPProviderPlugin):
    name="airtable"; description="Airtable Web API base and schema discovery."
    base_url="https://api.airtable.com/v0"
    version_info=VersionInfo(configured="v0",api_family="Web API",api_version="v0",supported=("v0",),recommended="v0",compatibility="supported",source="official Airtable Web API documentation")
    actions=(ProviderAction("airtable.status","/meta/bases?pageSize=1",api_version="v0"),ProviderAction("airtable.base.list","/meta/bases","bases",api_version="v0"),ProviderAction("airtable.base.inspect","/meta/bases/{base_id}/tables",parameters=("base_id",),api_version="v0"),ProviderAction("airtable.table.list","/meta/bases/{base_id}/tables","tables",("base_id",),api_version="v0"))
