# SPDX-License-Identifier: MPL-2.0
from .provider import HTTPProviderPlugin, ProviderAction
from ..axp import VersionInfo

class Plugin(HTTPProviderPlugin):
    name="paddle"; description="Paddle billing: customers, transactions, products, prices, subscriptions."
    base_url="https://api.paddle.com"
    version_info=VersionInfo(configured="v1",api_family="REST",api_version="v1",supported=("v1",),recommended="v1",compatibility="supported",source="official Paddle API reference")
    actions=(ProviderAction("paddle.status","/customers?per_page=1","data"),ProviderAction("paddle.customer.list","/customers","data"),ProviderAction("paddle.product.list","/products","data"),ProviderAction("paddle.price.list","/prices","data"),ProviderAction("paddle.subscription.list","/subscriptions","data"),ProviderAction("paddle.transaction.list","/transactions","data"))
