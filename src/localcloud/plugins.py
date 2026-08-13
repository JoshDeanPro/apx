from __future__ import annotations

from typing import Protocol, TYPE_CHECKING

if TYPE_CHECKING:
    from .actions import ActionRegistry


class Plugin(Protocol):
    name: str
    def register(self, actions: "ActionRegistry") -> None: ...


def load_entrypoint_plugins(registry: "ActionRegistry") -> list[str]:
    from importlib.metadata import entry_points
    loaded = []
    for point in entry_points(group="localcloud.plugins"):
        plugin = point.load()()
        plugin.register(registry)
        loaded.append(point.name)
    return loaded

