# SPDX-License-Identifier: MPL-2.0
"""Deterministic local filesystem 'ensure' actions.

These exist so Blueprints (see blueprints.py) have real desired-state primitives to
compose instead of shelling out to mkdir/echo. Each supports dry_run (used by
blueprint.plan) and reports changed=False when the filesystem already matches the
requested state -- the same "ensure" idiom CoreActions.service_control already uses.
"""
from __future__ import annotations

from typing import Any

from .actions import ActionError
from .files import atomic_write, normalized

_MODES = ("safe", "overwrite")


def directory_ensure(path: str, dry_run: bool = False) -> dict[str, Any]:
    target = normalized(path)
    if target.exists():
        if not target.is_dir(): raise ActionError(f"{target} exists and is not a directory")
        return {"path": str(target), "changed": False, "dry_run": dry_run, "summary": f"{target} already exists"}
    if dry_run: return {"path": str(target), "changed": True, "dry_run": True, "summary": f"would create {target}"}
    target.mkdir(parents=True, exist_ok=True)
    return {"path": str(target), "changed": True, "dry_run": False, "summary": f"created {target}"}


def file_template_ensure(path: str, content: str, mode: str = "safe", dry_run: bool = False) -> dict[str, Any]:
    if mode not in _MODES: raise ActionError(f"invalid mode {mode!r}; expected one of {_MODES}")
    target = normalized(path)
    if target.exists():
        if target.is_dir(): raise ActionError(f"{target} exists and is a directory")
        existing = target.read_text(encoding="utf-8")
        if existing == content:
            return {"path": str(target), "changed": False, "dry_run": dry_run, "summary": f"{target} already matches"}
        if mode == "safe":
            return {"path": str(target), "changed": False, "skipped": True, "dry_run": dry_run,
                     "summary": f"{target} exists with different content; not overwritten (mode=safe)"}
    if dry_run: return {"path": str(target), "changed": True, "dry_run": True, "summary": f"would write {target}"}
    target.parent.mkdir(parents=True, exist_ok=True)
    atomic_write(target, content, mode=0o644)
    return {"path": str(target), "changed": True, "dry_run": False, "summary": f"wrote {target}"}


def file_exists(path: str) -> dict[str, Any]:
    target = normalized(path)
    return {"path": str(target), "exists": target.exists(), "is_dir": target.is_dir() if target.exists() else None}
