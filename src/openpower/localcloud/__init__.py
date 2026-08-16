# SPDX-License-Identifier: MPL-2.0
"""OpenPower LocalCloud runtime.

LocalCloud is the operational layer built on the APX protocol.  It owns local
runtime concerns such as host orchestration, local state, credentials/vault UX,
and the interactive environment.  APX remains usable independently.
"""
from __future__ import annotations

from typing import Any

from apx.cloud import APX

from .vault import (
    localcloud_get,
    localcloud_set,
    localcloud_status,
    localcloud_sync_peer,
)


class LocalCloud:
    """Thin OpenPower runtime facade over an APX action fabric.

    The facade deliberately composes APX rather than subclassing it so the
    protocol package does not acquire a dependency on OpenPower/LocalCloud.
    """

    def __init__(self, config: str | None = None):
        self._apx = APX(config)

    def run(self, action: str, actor: str | None = None, **inputs: Any):
        return self._apx.run(action, actor=actor, **inputs)

    def resources(self):
        return self._apx.resources()

    def relationships(self):
        return self._apx.relationships()

    def action_definitions(self):
        actions = getattr(self._apx, "actions", None)
        if actions is not None and hasattr(actions, "list"):
            return actions.list()
        method = getattr(self._apx, "action_definitions", None)
        return method() if callable(method) else []

    @property
    def events(self):
        return self._apx.events

    def status(self) -> dict[str, Any]:
        return localcloud_status()

    def secret_get(self, key: str, default: Any = None) -> Any:
        return localcloud_get(key, default)

    def secret_set(self, key: str, value: Any, metadata: dict[str, Any] | None = None) -> dict[str, Any]:
        return localcloud_set(key, value, metadata)

    def sync_peer(self, peer_id: str, host: str, token: str) -> dict[str, Any]:
        return localcloud_sync_peer(peer_id, host, token)


__all__ = [
    "LocalCloud",
    "localcloud_get",
    "localcloud_set",
    "localcloud_status",
    "localcloud_sync_peer",
]
