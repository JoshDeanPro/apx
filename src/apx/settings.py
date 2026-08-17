# SPDX-License-Identifier: MIT
from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any

from . import __version__
from .config import apx_home, default_config_path, is_source_checkout, load_document, state_files


def get_document(config_path: Path | None = None) -> tuple[Path, dict[str, Any]]:
    path = Path(config_path).expanduser() if config_path else default_config_path()
    if path.exists():
        try:
            return load_document(path)
        except Exception:
            return path, {}
    return path, {}


def get_all_settings(config_path: Path | None = None) -> dict[str, Any]:
    resolved_path, doc = get_document(config_path)
    existing_state = [str(p) for p in state_files(resolved_path) if p.exists()]

    return {
        "version": __version__,
        "runtime": {
            "kind": "python",
            "prefix": sys.prefix,
        },
        "paths": {
            "home": str(apx_home()),
            "config": str(resolved_path),
            "config_exists": resolved_path.exists(),
            "in_source_checkout": is_source_checkout(resolved_path),
            "state_files": existing_state,
        },
        "node": {
            "name": (doc.get("node") or {}).get("name"),
            "default_actor": doc.get("default_actor", "human:operator"),
        },
        "integrations": {
            "plugins": list((doc.get("plugins") or {}).keys()),
            "connections": [c.get("id") for c in doc.get("connections", []) if isinstance(c, dict)],
        },
    }


def format_settings(data: dict[str, Any]) -> str:
    v = data["version"]
    runtime_kind = data["runtime"]["kind"]
    runtime_root = data["runtime"].get("prefix", "")
    config_path = data["paths"]["config"]
    config_exists = "exists" if data["paths"]["config_exists"] else "not created (run `apx init`)"
    node_name = data["node"]["name"] or "auto-detected"
    default_actor = data["node"]["default_actor"]

    lines = [
        "APX Settings & Environment",
        "─" * 60,
        f"  Version:        APX {v}",
        f"  Runtime:        {runtime_kind} ({runtime_root})",
        f"  APX Home:       {data['paths']['home']}",
        f"  Config:         {config_path} [{config_exists}]",
        f"  Node:           {node_name}",
        f"  Default Actor:  {default_actor}",
        "",
        "Settings Commands:",
        "  apx settings get <key>      Read a specific setting value",
        "  apx settings set <k> <v>    Persist a setting value into config",
        "─" * 60,
    ]
    return "\n".join(lines)


def get_setting(key: str, config_path: Path | None = None) -> Any:
    _, doc = get_document(config_path)
    parts = key.split(".")
    current: Any = doc
    for part in parts:
        if isinstance(current, dict) and part in current:
            current = current[part]
        else:
            return None
    return current


def set_setting(key: str, value: str, config_path: Path | None = None) -> dict[str, Any]:
    resolved_path, doc = get_document(config_path)
    if not resolved_path.exists():
        resolved_path.parent.mkdir(parents=True, exist_ok=True)
        content = ""
    else:
        content = resolved_path.read_text(encoding="utf-8")

    # Coerce boolean and integer values
    parsed_val: Any = value
    if value.lower() in ("true", "yes", "on"):
        parsed_val = True
    elif value.lower() in ("false", "no", "off"):
        parsed_val = False
    elif value.isdigit():
        parsed_val = int(value)

    # Convert key format: section.key
    parts = key.split(".", 1)
    section = parts[0] if len(parts) == 2 else "settings"
    subkey = parts[1] if len(parts) == 2 else parts[0]

    val_repr = "true" if parsed_val is True else "false" if parsed_val is False else f'"{parsed_val}"' if isinstance(parsed_val, str) else str(parsed_val)

    section_header = f"[{section}]"
    if section_header in content:
        lines = content.splitlines()
        in_section = False
        replaced = False
        new_lines = []
        for line in lines:
            stripped = line.strip()
            if stripped == section_header:
                in_section = True
                new_lines.append(line)
                continue
            if in_section and stripped.startswith("["):
                # End of target section without finding key, insert before new section
                if not replaced:
                    new_lines.append(f"{subkey} = {val_repr}")
                    replaced = True
                in_section = False
            elif in_section and (stripped.startswith(f"{subkey} ") or stripped.startswith(f"{subkey}=")):
                new_lines.append(f"{subkey} = {val_repr}")
                replaced = True
                continue
            new_lines.append(line)
        if in_section and not replaced:
            new_lines.append(f"{subkey} = {val_repr}")
        content = "\n".join(new_lines) + "\n"
    else:
        content = content.rstrip() + f"\n\n[{section}]\n{subkey} = {val_repr}\n"

    resolved_path.write_text(content, encoding="utf-8")
    return {"ok": True, "key": key, "value": parsed_val, "config": str(resolved_path)}

