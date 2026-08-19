# SPDX-License-Identifier: MIT
"""Narrow read-only inventory views for configured APX providers."""
from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any
from urllib.parse import urlsplit, urlunsplit

from .axp import APX_PROTOCOL_VERSION, StructuredError, resource_ref
from .health import ComponentHealth
from .providers import ActionProvider, ProviderManifest, RemoteProvider


ProviderLike = ActionProvider | RemoteProvider


def _safe_endpoint(value: str | None) -> str | None:
    if not value:
        return None
    parsed = urlsplit(value)
    if not parsed.scheme or not parsed.hostname:
        return None
    hostname = parsed.hostname
    if ":" in hostname and not hostname.startswith("["):
        hostname = f"[{hostname}]"
    netloc = hostname
    if parsed.port:
        netloc += f":{parsed.port}"
    return urlunsplit((parsed.scheme, netloc, parsed.path, parsed.query, ""))


@dataclass(frozen=True)
class ServerInventory:
    """Secret-free observation of one configured APX provider/server."""

    id: str
    name: str
    reference: str
    provider_id: str
    endpoint: str | None
    status: str
    health: ComponentHealth
    protocol_version: str
    manifest_version: str
    implementation_version: str | None
    action_count: int
    available_actions: tuple[str, ...]
    unavailable_actions: tuple[str, ...]
    capabilities: tuple[str, ...]
    required_credentials: tuple[str, ...]
    required_permissions: tuple[str, ...]
    allowed_actor_types: tuple[str, ...]
    error: StructuredError | None = None

    @classmethod
    def from_provider(cls, provider: ProviderLike) -> "ServerInventory":
        manifest: ProviderManifest = provider.manifest()
        health = provider.health()
        implementation_version = manifest.metadata.get("version") if isinstance(manifest.metadata, dict) else None
        if implementation_version is not None and not isinstance(implementation_version, str):
            implementation_version = str(implementation_version)
        return cls(
            id=manifest.provider.id,
            name=manifest.provider.name,
            reference=resource_ref("server", manifest.provider.id),
            provider_id=manifest.provider.id,
            endpoint=_safe_endpoint(manifest.provider.url),
            status=health.status,
            health=health,
            protocol_version=manifest.apx_version,
            manifest_version=manifest.manifest_version,
            implementation_version=implementation_version,
            action_count=len(manifest.actions),
            available_actions=tuple(sorted(action.id for action in manifest.actions if action.available)),
            unavailable_actions=tuple(sorted(manifest.unavailable_actions)),
            capabilities=tuple(sorted(manifest.capabilities)),
            required_credentials=tuple(sorted(manifest.required_credentials)),
            required_permissions=tuple(sorted(manifest.required_permissions)),
            allowed_actor_types=tuple(sorted(manifest.allowed_actor_types)),
        )

    @classmethod
    def unavailable(cls, provider: ProviderLike, error: StructuredError) -> "ServerInventory":
        identity = getattr(provider, "identity", None) or getattr(provider, "_manifest").provider
        provider_id = identity.id
        health = ComponentHealth(f"provider:{provider_id}", "unavailable", error.message)
        return cls(
            id=provider_id,
            name=provider.identity.name,
            reference=resource_ref("server", provider_id),
            provider_id=provider_id,
            endpoint=_safe_endpoint(provider.identity.url),
            status="unavailable",
            health=health,
            protocol_version=APX_PROTOCOL_VERSION,
            manifest_version=APX_PROTOCOL_VERSION,
            implementation_version=None,
            action_count=0,
            available_actions=(),
            unavailable_actions=(),
            capabilities=(),
            required_credentials=(),
            required_permissions=(),
            allowed_actor_types=(),
            error=error,
        )

    def to_dict(self) -> dict[str, Any]:
        value = asdict(self)
        value["health"] = self.health.to_dict()
        value["error"] = self.error.to_dict() if self.error else None
        return value
