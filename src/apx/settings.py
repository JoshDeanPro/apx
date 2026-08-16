# SPDX-License-Identifier: MPL-2.0
from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any

from . import __version__
from .config import apx_home, default_config_path, is_source_checkout, load_document, state_files
from .doctor import diagnose, summarize
from .selfupdate import apply_update, auto_check_updates, check_for_updates, installation, push_to_host, update_source, version_info


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
    version = version_info()
    where = installation()
    update_cfg = doc.get("update") or {}
    settings_cfg = doc.get("settings") or {}
    auto_check = settings_cfg.get("auto_update_check", update_cfg.get("auto_check", True))

    configured_source = update_source(config=doc)
    existing_state = [str(p) for p in state_files(resolved_path) if p.exists()]
    update_status = auto_check_updates(config=doc)

    return {
        "version": __version__,
        "git": version.get("git"),
        "runtime": where,
        "paths": {
            "home": str(apx_home()),
            "config": str(resolved_path),
            "config_exists": resolved_path.exists(),
            "in_source_checkout": is_source_checkout(resolved_path),
            "state_files": existing_state,
        },
        "node": {
            "name": (doc.get("node") or {}).get("name"),
            "default_actor": doc.get("default_actor", "human:ethan"),
        },
        "update": {
            "source": configured_source,
            "auto_check": auto_check,
            "status": update_status,
        },
        "integrations": {
            "plugins": list((doc.get("plugins") or {}).keys()),
            "channels": list((doc.get("channels") or {}).keys()),
        },
    }


def format_settings(data: dict[str, Any]) -> str:
    v = data["version"]
    git = data.get("git") or {}
    git_str = f" (commit: {git.get('commit')}, branch: {git.get('branch')})" if git.get("commit") else ""
    runtime_kind = data["runtime"]["kind"]
    runtime_root = data["runtime"].get("root") or data["runtime"].get("prefix", "")
    config_path = data["paths"]["config"]
    config_exists = "exists" if data["paths"]["config_exists"] else "not created (run `apx init`)"
    node_name = data["node"]["name"] or "auto-detected"
    default_actor = data["node"]["default_actor"]
    update_source_val = data["update"]["source"] or "default (git upstream / wheel release)"
    auto_check_val = "enabled (checks on launch)" if data["update"]["auto_check"] else "disabled"
    up_status = data["update"].get("status") or {}
    if up_status.get("update_available"):
        commits = up_status.get("commits_behind", 0)
        status_text = f"UPDATE AVAILABLE ({commits} commit{'s' if commits != 1 else ''} behind {up_status.get('upstream', '')})"
    elif up_status.get("disabled"):
        status_text = "auto-check disabled"
    else:
        status_text = "up to date"

    lines = [
        "APX Settings & Environment",
        "─" * 60,
        f"  Version:        APX {v}{git_str}",
        f"  Runtime:        {runtime_kind} ({runtime_root})",
        f"  APX Home:       {data['paths']['home']}",
        f"  Config:         {config_path} [{config_exists}]",
        f"  Node:           {node_name}",
        f"  Default Actor:  {default_actor}",
        "",
        "Update & Diagnostics:",
        f"  Update Source:  {update_source_val}",
        f"  Auto-Check:     {auto_check_val}",
        f"  Update Status:  {status_text}",
        "",
        "Settings Commands:",
        "  apx settings doctor         Run full environment & node diagnosis",
        "  apx settings update [check] Check for updates or apply with `apx settings update apply`",
        "  apx settings get <key>      Read a specific setting value (e.g. update.auto_check)",
        "  apx settings set <k> <v>    Persist a setting value into config.toml",
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
            elif in_section and stripped.startswith(f"{subkey} ") or stripped.startswith(f"{subkey}="):
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


def execute_settings_doctor(config_path: Path | None = None, json_output: bool = False) -> int:
    report = diagnose(config_path)
    if json_output:
        print(json.dumps(report, indent=2, ensure_ascii=False))
    else:
        print(summarize(report))
    return 0 if report.get("ok") else 1


def execute_settings_update(verb: str = "check", source: str | None = None, reinstall: bool = True, hosts: list[str] | None = None, config_path: Path | None = None, json_output: bool = False) -> int:
    from .selfupdate import UpdateError
    _, doc = get_document(config_path)
    if verb == "check":
        res = check_for_updates(source=source, config=doc)
        if json_output:
            print(json.dumps(res, indent=2, ensure_ascii=False))
        else:
            if res.get("update_available"):
                commits = res.get("commits_behind", 1)
                upstream = res.get("upstream", "upstream")
                print(f"\n[APX] Update Available: {commits} new commit{'s' if commits != 1 else ''} ({upstream}).")
                print("Run `apx update` or `apx settings update apply` to install.\n")
            elif res.get("disabled"):
                print(f"\n[APX] Update check is disabled in configuration.\n")
            elif res.get("error"):
                print(f"\n[APX] Could not check for updates: {res['error']}\n")
            else:
                print(f"\n[APX] APX is up to date! (Version {__version__})\n")
        return 0
    if verb == "push":
        from .config import load
        try:
            hosts_dict, _ = load(config_path)
            targets = [hosts_dict[name] for name in (hosts or [h for h, v in hosts_dict.items() if not v.is_self])]
        except KeyError as error:
            if json_output: print(json.dumps({"ok": False, "error": f"unknown host {error}"}, indent=2))
            else: print(f"Error: unknown host {error}")
            return 2
        except Exception as error:
            if json_output: print(json.dumps({"ok": False, "error": str(error)}, indent=2))
            else: print(f"Error: {error}")
            return 1
        results, failures = [], 0
        for host in targets:
            try:
                r = push_to_host(host)
                results.append(r)
                if not json_output:
                    print(f"✓ Successfully published APX to {host.name} (version {r.get('version')})")
            except UpdateError as error:
                results.append({"host": host.name, "ok": False, "error": str(error)})
                failures += 1
                if not json_output:
                    print(f"✗ Failed to publish to {host.name}: {error}")
        if json_output:
            print(json.dumps({"ok": failures == 0, "nodes": results}, indent=2))
        return 1 if failures else 0
    try:
        res = apply_update(reinstall=reinstall, source=source, config=doc)
        if json_output:
            print(json.dumps(res, indent=2, ensure_ascii=False))
        else:
            if res.get("updated"):
                print(f"\n[APX] Successfully updated APX! ({res.get('before')} → {res.get('after')})\n")
            else:
                print(f"\n[APX] APX is already up to date ({__version__}).\n")
        return 0
    except UpdateError as error:
        if json_output:
            print(json.dumps({"ok": False, "error": str(error)}, indent=2))
        else:
            print(f"\n[APX] Update failed: {error}\n")
        return 1
