# SPDX-License-Identifier: MIT
"""Small user-owned resource group/tag overlay; no database required."""
from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

from .axp import Resource
from .files import atomic_write

class GroupStore:
    def __init__(self,config_path: Path,configured: dict | None = None):
        self.path=config_path.with_suffix(".groups.json"); self.configured=configured or {}; self.overlay=self._load()

    def _load(self):
        if not self.path.exists(): return {}
        try: return json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError,json.JSONDecodeError): return {}

    def apply(self,resource: Resource) -> Resource:
        configured=self.configured.get(resource.id,{}); overlay=self.overlay.get(resource.id,{})
        groups=tuple(dict.fromkeys((*resource.groups,*configured.get("groups",()),*overlay.get("groups",()))))
        tags=tuple(dict.fromkeys((*resource.tags,*configured.get("tags",()),*overlay.get("tags",()))))
        return replace(resource,groups=groups,tags=tags)

    def change(self,resource: str,group: str,add: bool) -> dict:
        if not group or any(char.isspace() for char in group): raise ValueError("group must be a non-empty identifier without whitespace")
        entry=self.overlay.setdefault(resource,{"groups":[],"tags":[]}); groups=entry["groups"]
        if add and group not in groups: groups.append(group)
        if not add and group in groups: groups.remove(group)
        atomic_write(self.path,json.dumps(self.overlay,indent=2)+"\n")
        return {"resource":resource,"group":group,"member":add,"storage":str(self.path)}
