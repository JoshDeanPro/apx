from __future__ import annotations

import json
import os
import urllib.request
from dataclasses import dataclass
from typing import Any, Callable

from ..axp import Event
from ..plugins import PluginAPI

DEFAULT_PATTERNS=("project.deployed","backup.completed","service.failed")


def _send(url: str, payload: dict[str,Any]) -> None:
    request=urllib.request.Request(url,data=json.dumps(payload).encode(),headers={"Content-Type":"application/json","User-Agent":"localcloud/0.1"},method="POST")
    with urllib.request.urlopen(request,timeout=10) as response:
        if response.status not in {200,204}: raise RuntimeError(f"Discord webhook returned HTTP {response.status}")


@dataclass
class DiscordWebhookPlugin:
    webhook_url: str
    patterns: tuple[str,...] = DEFAULT_PATTERNS
    sender: Callable[[str,dict[str,Any]],None] = _send
    name: str = "discord_webhook"

    @classmethod
    def from_config(cls, config: dict[str,Any]) -> "DiscordWebhookPlugin":
        variable=config.get("url_env","LOCALCLOUD_DISCORD_WEBHOOK_URL")
        url=os.environ.get(variable,"")
        if not url: raise ValueError(f"Discord webhook plugin requires environment variable {variable}")
        if not url.startswith("https://"): raise ValueError("Discord webhook URL must use HTTPS")
        return cls(url,tuple(config.get("events",DEFAULT_PATTERNS)))

    def setup(self, api: PluginAPI) -> None:
        for pattern in self.patterns: api.subscribe(pattern,self.on_event)

    def on_event(self, event: Event) -> None:
        subject=", ".join(f"{key}={value}" for key,value in event.subject.items()) or "localcloud"
        content=f"LOCALCLOUD: {event.name} ({subject})"
        self.sender(self.webhook_url,{"content":content[:2000],"allowed_mentions":{"parse":[]}})
