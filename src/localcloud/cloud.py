from __future__ import annotations

from pathlib import Path
from typing import Any

from .actions import ActionError, CoreActions, build_registry
from .config import load
from .models import ActionResult
from .plugins import load_entrypoint_plugins


class LocalCloud:
    """Python API. CLI and MCP both delegate to this exact action path."""

    def __init__(self, config: str | Path | None = None, *, plugins: bool = True):
        self.hosts, self.projects = load(config)
        self.core = CoreActions(self.hosts, self.projects)
        self.actions = build_registry(self.core)
        self.plugins = load_entrypoint_plugins(self.actions) if plugins else []

    def run(self, action: str, **inputs: Any) -> ActionResult:
        try:
            definition = self.actions.get(action)
            data = definition.handler(**inputs)
            return ActionResult(action=action, ok=True, data=data, host=inputs.get("host"))
        except (ActionError, RuntimeError, OSError, ValueError) as error:
            return ActionResult(action=action, ok=False, error=str(error), host=inputs.get("host"))

