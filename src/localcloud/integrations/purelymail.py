"""Purelymail is POST-only and reports failure in the response body rather
than the HTTP status, so every call here is unwrapped before it's returned
-- doesn't fit HTTPProviderPlugin's GET/path-substitution ProviderAction
shape, so actions are registered directly in setup(), same pattern as
discord.py's webhook/message extensions.
"""
from __future__ import annotations

from dataclasses import replace
from .provider import HTTPProviderPlugin
from ..actions import RegisteredAction
from ..axp import VersionInfo


class Plugin(HTTPProviderPlugin):
    name="purelymail"; description="Purelymail account administration: domains, mailboxes, forwarding aliases."
    base_url="https://purelymail.com/api/v0"
    version_info=VersionInfo(configured="v0",api_family="REST",api_version="v0",supported=("v0",),recommended="v0",compatibility="supported",source="official Purelymail API reference")
    credential_headers=(("credential","Purelymail-Api-Token",""),)
    actions=()

    @property
    def metadata(self):
        metadata=super().metadata
        return replace(metadata,actions=metadata.actions+("purelymail.status","purelymail.domain.list","purelymail.mailbox.list"))

    def _call(self, endpoint: str, body: dict | None = None):
        response=self.http.request("POST",f"{self.base_url}/{endpoint}",headers=self.headers(),body=body or {})
        result=response.body
        if not isinstance(result,dict): raise RuntimeError(f"purelymail {endpoint}: unexpected response {str(result)[:200]}")
        if result.get("type")=="error" or result.get("error"):
            raise RuntimeError(f"purelymail {endpoint} failed: {result.get('message') or result.get('error')}")
        return result.get("result",result)

    def setup(self, api) -> None:
        super().setup(api)
        empty_schema={"type":"object","properties":{},"additionalProperties":False}

        def status(): return self._call("listDomains")
        api.register_action(RegisteredAction("purelymail.status","Verify the Purelymail credential works",status,empty_schema))

        def domain_list(): return self._call("listDomains")
        api.register_action(RegisteredAction("purelymail.domain.list","List domains on this Purelymail account",domain_list,empty_schema))

        def mailbox_list(): return self._call("listUsers")
        api.register_action(RegisteredAction("purelymail.mailbox.list","List mailboxes on this Purelymail account",mailbox_list,empty_schema))
