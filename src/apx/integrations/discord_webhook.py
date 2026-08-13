# SPDX-License-Identifier: MPL-2.0
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

from ..axp import Event
from ..plugins import PluginAPI
from ..plugins import PluginMetadata
from ..adapters.http import HTTPAdapter

DEFAULT_PATTERNS=("project.deployed","backup.completed","service.failed")


@dataclass
class DiscordWebhookPlugin:
    credential_id: str
    patterns: tuple[str,...] = DEFAULT_PATTERNS
    sender: Callable[[str,dict[str,Any]],None] | None = None
    name: str = "discord_webhook"
    metadata=PluginMetadata("discord_webhook","0.2.0","Send selected AXP events through a Discord webhook.",events_listened=DEFAULT_PATTERNS,credentials=("discord_webhook",))

    def __post_init__(self) -> None:
        # Metadata follows a configured reference name without resolving it.
        self.metadata = PluginMetadata(
            "discord_webhook",
            "0.2.0",
            "Send selected AXP events through a Discord webhook.",
            events_listened=self.patterns,
            credentials=(self.credential_id,),
        )

    @classmethod
    def from_config(cls, config: dict[str,Any]) -> "DiscordWebhookPlugin":
        credential=config.get("credential","discord_webhook")
        return cls(credential,tuple(config.get("events",DEFAULT_PATTERNS)))

    def setup(self, api: PluginAPI) -> None:
        self._api=api
        for pattern in self.patterns: api.subscribe(pattern,self.on_event)

    def on_event(self, event: Event) -> None:
        subject=", ".join(f"{key}={value}" for key,value in event.subject.items()) or "apx"
        content=f"APX: {event.name} ({subject})"
        url=self._api.credential(self.credential_id)
        if not url.startswith("https://"): raise ValueError("Discord webhook URL must use HTTPS")
        payload={"content":content[:2000],"allowed_mentions":{"parse":[]}}
        if self.sender: self.sender(url,payload)
        else: HTTPAdapter(self._api.cloud.credentials).request("POST",url,body=payload,credential=None,timeout=10)
