# SPDX-License-Identifier: MIT
from __future__ import annotations

from .base import AdapterMetadata
from .http import HTTPAdapter
from ..axp import Event


class WebhookAdapter:
    metadata=AdapterMetadata("webhook","0.1","Send AXP events to HTTPS webhook endpoints.",( "webhook",))

    def __init__(self,http: HTTPAdapter): self.http=http

    def send(self,url: str,event: Event,*,credential: str | None = None,headers: dict[str,str] | None = None,timeout: int = 15):
        return self.http.request("POST",url,headers=headers,body=event.to_dict(),credential=credential,timeout=timeout)

    def health(self): return {"ok":True,"adapter":"webhook","inbound_supported":False}
