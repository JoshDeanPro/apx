# SPDX-License-Identifier: MIT
from __future__ import annotations

from dataclasses import replace
from .provider import HTTPProviderPlugin, ProviderAction
from ..actions import RegisteredAction
from ..axp import VersionInfo

class Plugin(HTTPProviderPlugin):
    name="discord"; description="Discord application, guild, bot, and webhook operations without a bot framework."
    base_url="https://discord.com/api/v10"
    version_info=VersionInfo(configured="v10",api_family="REST",api_version="v10",supported=("v10",),recommended="v10",compatibility="supported",source="official Discord developer documentation")
    credential_headers=(("bot_credential","Authorization","Bot "),)
    actions=(ProviderAction("discord.status","/users/@me",api_version="v10"),ProviderAction("discord.application.inspect","/oauth2/applications/@me",api_version="v10"),ProviderAction("discord.guild.list","/users/@me/guilds",api_version="v10"),ProviderAction("discord.role.list","/guilds/{guild_id}/roles",parameters=("guild_id",),api_version="v10"),ProviderAction("discord.member.list","/guilds/{guild_id}/members",parameters=("guild_id",),api_version="v10"),ProviderAction("discord.audit_log.list","/guilds/{guild_id}/audit-logs",parameters=("guild_id",),api_version="v10"),ProviderAction("discord.invite.list","/guilds/{guild_id}/invites",parameters=("guild_id",),api_version="v10"),ProviderAction("discord.command.list","/applications/{application_id}/commands",parameters=("application_id",),api_version="v10"))

    @property
    def metadata(self):
        metadata=super().metadata
        return replace(metadata,actions=metadata.actions+("discord.webhook.health","discord.webhook.send","discord.message.send"))

    def setup(self,api):
        super().setup(api)
        schema={"type":"object","properties":{"credential":{"type":"string"}},"additionalProperties":False}
        def webhook_health(credential=None):
            selected=credential or self.config.get("webhook_credential")
            health=next((item for item in api.cloud.credentials.health() if item["id"]==selected),None)
            return {"credential":selected,"configured":health is not None,"available":bool(health and health["available"])}
        api.register_action(RegisteredAction("discord.webhook.health","Check a configured Discord webhook reference",webhook_health,schema))
        send_schema={"type":"object","properties":{"credential":{"type":"string"},"content":{"type":"string","maxLength":2000}},"required":["content"],"additionalProperties":False}
        def send(content: str,credential: str | None = None):
            reference=credential or self.config.get("webhook_credential")
            if not reference: raise ValueError("Discord webhook credential reference is not configured")
            url=api.credential(reference)
            response=self.http.request("POST",url,body={"content":content[:2000],"allowed_mentions":{"parse":[]}})
            return {"sent":response.status in {200,204}}
        api.register_action(RegisteredAction("discord.webhook.send","Send a Discord webhook message",send,send_schema,False,False))
        message_schema={"type":"object","properties":{"channel_id":{"type":"string"},"content":{"type":"string","maxLength":2000}},"required":["channel_id","content"],"additionalProperties":False}
        def message_send(channel_id: str,content: str):
            response=self.http.request("POST",self.base_url+f"/channels/{channel_id}/messages",headers=self.headers(),body={"content":content[:2000],"allowed_mentions":{"parse":[]}})
            return {"sent":response.status==200,"message":response.body}
        api.register_action(RegisteredAction("discord.message.send","Send a Discord channel message",message_send,message_schema,False,False))
