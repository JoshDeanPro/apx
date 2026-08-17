# SPDX-License-Identifier: MIT
from __future__ import annotations

import re
from pathlib import Path


def _name(value: str) -> str:
    cleaned=re.sub(r"[^a-z0-9_]+","_",value.lower().replace("-","_"))
    if not cleaned or not re.match(r"[a-z_]",cleaned): raise ValueError("name must contain letters, numbers, dashes, or underscores")
    return cleaned


def create(kind: str, name: str, destination: str | Path = ".") -> dict:
    slug=_name(name); root=Path(destination).expanduser()/slug
    if root.exists(): raise FileExistsError(f"destination already exists: {root}")
    root.mkdir(parents=True)
    if kind=="plugin":
        files={
          "pyproject.toml":f'''[build-system]\nrequires=["setuptools>=68"]\nbuild-backend="setuptools.build_meta"\n\n[project]\nname="apx-{slug}"\nversion="0.1.0"\ndependencies=[]\n\n[project.entry-points."apx.plugins"]\n{slug}="{slug}.plugin:Plugin"\n''',
          f"{slug}/__init__.py":"",
          f"{slug}/plugin.py":f'''from apx.actions import RegisteredAction\nfrom apx.plugins import PluginMetadata\n\nclass Plugin:\n    name="{slug}"\n    # Add credentials=("{slug}",) if this integration requires that reference.\n    metadata=PluginMetadata(name, "0.1.0", "A APX plugin.", actions=("{slug}.inspect",))\n\n    def setup(self, api):\n        def inspect():\n            # Resolve only inside an action when this integration needs it:\n            # secret = api.credential("{slug}")\n            return {{"plugin": self.name, "ready": True}}\n        api.register_action(RegisteredAction("{slug}.inspect", "Inspect {slug}", inspect, {{"type":"object","properties":{{}},"additionalProperties":False}}))\n''',
          "tests/test_plugin.py":f'''import unittest\nfrom {slug}.plugin import Plugin\n\nclass PluginTests(unittest.TestCase):\n    def test_metadata(self): self.assertEqual(Plugin.metadata.apx, "0.1")\n'''}
    elif kind=="action":
        action=name if "." in name else f"custom.{slug}"
        files={"action.py":f'''from apx.actions import ActionError, RegisteredAction\n\ndef handler(value: str):\n    if not value: raise ActionError("value is required")\n    return {{"value": value}}\n\naction=RegisteredAction("{action}", "Describe {action}", handler, {{"type":"object","properties":{{"value":{{"type":"string"}}}},"required":["value"],"additionalProperties":False}})\n''',"test_action.py":'''import unittest\nfrom action import action\n\nclass ActionTests(unittest.TestCase):\n    def test_handler(self): self.assertTrue(action.handler(value="example"))\n'''}
    elif kind=="adapter":
        files={"adapter.py":f'''from apx.adapters import AdapterMetadata\n\nclass {slug.title().replace('_','')}Adapter:\n    metadata=AdapterMetadata("{slug}", "0.1.0", "Connect to {slug}.", ("{slug}",))\n    def health(self): return {{"ok": True, "adapter": self.metadata.name}}\n''',"test_adapter.py":f'''import unittest\nfrom adapter import {slug.title().replace('_','')}Adapter\n\nclass AdapterTests(unittest.TestCase):\n    def test_health(self): self.assertTrue({slug.title().replace('_','')}Adapter().health()["ok"])\n'''}
    else: raise ValueError("kind must be plugin, action, or adapter")
    for relative,content in files.items():
        path=root/relative; path.parent.mkdir(parents=True,exist_ok=True); path.write_text(content,encoding="utf-8")
    return {"kind":kind,"name":name,"path":str(root),"files":sorted(files)}
