# SPDX-License-Identifier: MIT
"""Blueprints: versioned, composable, idempotent graphs of existing APX actions.

A Blueprint does not invent a second execution engine. Every step re-enters
`APX.run()` exactly like a Procedure step does (see execution.py / cloud.py's
_execute_procedure) -- so policy, schema validation, and confirmation are enforced
per step, not once for the whole graph. Blueprints add three things Procedures
don't have: a DAG (not just a line), composition (`includes` other Blueprints),
and desired-state tracking (recorded per-project history + resulting capabilities
in BlueprintStore, mirroring MissionStore's JSON-overlay persistence).

No AI is required to run a Blueprint: everything here is deterministic Python.
"""
from __future__ import annotations

import json
import time
from dataclasses import dataclass, field, replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

from .execution import ProcedureFailed
from .files import atomic_write


class BlueprintError(RuntimeError): pass


def _now() -> str: return datetime.now(timezone.utc).isoformat()
def _id(prefix: str) -> str: return f"{prefix}-{uuid4().hex[:8]}"


def _version_key(version: str) -> tuple[int, ...]:
    parts = []
    for chunk in version.split("."):
        digits = "".join(ch for ch in chunk if ch.isdigit())
        parts.append(int(digits) if digits else 0)
    return tuple(parts) or (0,)


def _looks_sensitive(name: str) -> bool:
    lowered = name.lower()
    return any(word in lowered for word in ("secret", "password", "token", "credential", "api_key"))


@dataclass(frozen=True)
class BlueprintStep:
    id: str
    action: str
    args: dict[str, Any] = field(default_factory=dict)
    after: tuple[str, ...] = ()
    when: dict[str, Any] | None = None  # step only runs if resolved_inputs[k]==v for every k,v here

    def __post_init__(self) -> None:
        if not self.id: raise ValueError("a blueprint step requires an id")
        if not self.action: raise ValueError(f"step {self.id!r} requires an action")


@dataclass(frozen=True)
class Blueprint:
    stable_id: str
    name: str  # canonical, human-readable: "project/base-layout"
    version: str
    description: str
    steps: tuple[BlueprintStep, ...]
    aliases: tuple[str, ...] = ()
    category: str = "general"
    tags: tuple[str, ...] = ()
    inputs: dict[str, dict[str, Any]] = field(default_factory=dict)  # name -> {type, required, default}
    requires: tuple[str, ...] = ()  # soft capability requirements, checked against a project's recorded capabilities
    includes: tuple[str, ...] = ()  # other blueprint canonical names, composed in at resolve() time
    resulting_capabilities: tuple[str, ...] = ()
    provenance: str = "built_in"  # built_in | project | user | imported
    migrates_from: tuple[str, ...] = ()  # prior versions of this same canonical name this version can upgrade from

    def __post_init__(self) -> None:
        if not self.name: raise ValueError("a blueprint requires a canonical name")
        if not self.version: raise ValueError(f"blueprint {self.name!r} requires a version")
        if not self.steps: raise ValueError(f"blueprint {self.name!r} has no steps")
        ids = [step.id for step in self.steps]
        if len(ids) != len(set(ids)): raise ValueError(f"blueprint {self.name!r} has duplicate step ids")
        known = set(ids)
        for step in self.steps:
            unknown = [dep for dep in step.after if dep not in known]
            if unknown: raise ValueError(f"blueprint {self.name!r} step {step.id!r} depends on unknown step(s): {unknown}")

    def to_dict(self) -> dict[str, Any]:
        return {
            "stable_id": self.stable_id, "name": self.name, "version": self.version, "description": self.description,
            "aliases": list(self.aliases), "category": self.category, "tags": list(self.tags),
            "inputs": self.inputs, "requires": list(self.requires), "includes": list(self.includes),
            "resulting_capabilities": list(self.resulting_capabilities), "provenance": self.provenance,
            "migrates_from": list(self.migrates_from),
            "steps": [{"id": s.id, "action": s.action, "args": s.args, "after": list(s.after), "when": s.when} for s in self.steps],
        }

    def summary(self) -> dict[str, Any]:
        return {"stable_id": self.stable_id, "name": self.name, "version": self.version, "description": self.description,
                "category": self.category, "tags": list(self.tags), "requires": list(self.requires),
                "aliases": list(self.aliases), "includes": list(self.includes), "estimated_actions": len(self.steps)}


def toposort(steps: tuple[BlueprintStep, ...]) -> list[BlueprintStep]:
    by_id = {step.id: step for step in steps}
    order: list[BlueprintStep] = []
    visited: dict[str, int] = {}  # 0 = visiting, 1 = done

    def visit(step: BlueprintStep, chain: tuple[str, ...]) -> None:
        state = visited.get(step.id)
        if state == 1: return
        if state == 0: raise BlueprintError(f"cycle detected in blueprint steps: {' -> '.join(chain + (step.id,))}")
        visited[step.id] = 0
        for dep in step.after: visit(by_id[dep], chain + (step.id,))
        visited[step.id] = 1
        order.append(step)

    for step in steps: visit(step, ())
    return order


def compose(blueprint: "Blueprint", registry: "BlueprintRegistry") -> "Blueprint":
    """Recursively flattens `includes` into one execution graph.

    Steps are deduplicated by (action, args) signature -- if two included
    Blueprints (directly, or via a diamond of shared includes) both want to ensure
    the same thing, it is ensured once, not twice. Step ids are namespaced by their
    source blueprint to avoid collisions; a step with no explicit `after` implicitly
    depends on every step contributed by its own blueprint's direct includes, so
    "includes resolve before this blueprint's own logic" holds without every
    built-in Blueprint author having to spell out `after` by hand. Declared inputs
    are merged across the whole tree; the outermost (composing) blueprint's own
    declaration for a given input name wins, since its `add()` frame runs last.
    """
    if not blueprint.includes: return blueprint

    seen_signatures: dict[tuple[str, str], str] = {}
    flat_steps: list[BlueprintStep] = []
    requires: list[str] = []; tags: list[str] = []; resulting: list[str] = []
    merged_inputs: dict[str, dict[str, Any]] = {}
    resolved: dict[str, dict[str, str]] = {}  # blueprint name -> its local step id -> global step id

    def add(bp: "Blueprint", prefix: str, chain: tuple[str, ...]) -> dict[str, str]:
        if bp.name in chain: raise BlueprintError(f"include cycle detected: {' -> '.join(chain + (bp.name,))}")
        if bp.name in resolved: return resolved[bp.name]
        id_map: dict[str, str] = {}
        included_ids: set[str] = set()
        for included_name in bp.includes:
            included = registry.get(included_name)
            sub_map = add(included, f"{included.name}::", chain + (bp.name,))
            id_map.update(sub_map); included_ids.update(sub_map.values())
        local_new: list[BlueprintStep] = []
        for step in bp.steps:
            signature = (step.action, json.dumps(step.args, sort_keys=True))
            if signature in seen_signatures: id_map[step.id] = seen_signatures[signature]
            else:
                global_id = f"{prefix}{step.id}"
                seen_signatures[signature] = global_id; id_map[step.id] = global_id
                local_new.append(step)
        for step in local_new:
            after = tuple(sorted({id_map[dep] for dep in step.after})) if step.after else tuple(sorted(included_ids))
            flat_steps.append(replace(step, id=id_map[step.id], after=after))
        requires.extend(bp.requires); tags.extend(bp.tags); resulting.extend(bp.resulting_capabilities)
        for name, spec in bp.inputs.items(): merged_inputs[name] = spec
        resolved[bp.name] = id_map
        return id_map

    add(blueprint, f"{blueprint.name}::", ())
    return Blueprint(
        stable_id=blueprint.stable_id, name=blueprint.name, version=blueprint.version, description=blueprint.description,
        steps=tuple(flat_steps), aliases=blueprint.aliases, category=blueprint.category,
        tags=tuple(dict.fromkeys(tags)), inputs=merged_inputs, requires=tuple(dict.fromkeys(requires)),
        includes=blueprint.includes, resulting_capabilities=tuple(dict.fromkeys(resulting)),
        provenance=blueprint.provenance, migrates_from=blueprint.migrates_from,
    )


class BlueprintRegistry:
    """Mirrors ActionRegistry/ProcedureRegistry: register() validates every step
    references a real, currently-registered action before the Blueprint is trusted."""

    def __init__(self) -> None:
        self._by_key: dict[str, Blueprint] = {}  # "name@version" -> Blueprint
        self._latest: dict[str, str] = {}  # canonical name -> latest version string
        self._aliases: dict[str, str] = {}  # alias/stable_id -> canonical name
        self._resolved_cache: dict[str, Blueprint] = {}

    def register(self, blueprint: Blueprint, available_actions: set[str]) -> None:
        key = f"{blueprint.name}@{blueprint.version}"
        if key in self._by_key: raise BlueprintError(f"duplicate blueprint {key}")
        toposort(blueprint.steps)
        missing = [step.action for step in blueprint.steps if step.action not in available_actions]
        if missing: raise BlueprintError(f"blueprint {blueprint.name!r} references unknown action(s): {', '.join(sorted(set(missing)))}")
        self._by_key[key] = blueprint
        self._aliases[blueprint.stable_id] = blueprint.name
        for alias in blueprint.aliases: self._aliases[alias] = blueprint.name
        current = self._latest.get(blueprint.name)
        if current is None or _version_key(blueprint.version) > _version_key(current):
            self._latest[blueprint.name] = blueprint.version
        self._resolved_cache.pop(key, None)

    def canonical_name(self, name_or_alias: str) -> str: return self._aliases.get(name_or_alias, name_or_alias)

    def get(self, name: str, version: str | None = None) -> Blueprint:
        canonical = self.canonical_name(name)
        resolved_version = version or self._latest.get(canonical)
        key = f"{canonical}@{resolved_version}"
        if key not in self._by_key: raise BlueprintError(f"unknown blueprint {name!r}" + (f"@{version}" if version else ""))
        return self._by_key[key]

    def resolve(self, name: str, version: str | None = None) -> Blueprint:
        """Composed (includes flattened) and DAG-validated. Cached by exact key."""
        blueprint = self.get(name, version)
        cache_key = f"{blueprint.name}@{blueprint.version}"
        if cache_key not in self._resolved_cache:
            composed = compose(blueprint, self)
            toposort(composed.steps)
            self._resolved_cache[cache_key] = composed
        return self._resolved_cache[cache_key]

    def versions(self, name: str) -> list[str]:
        canonical = self.canonical_name(name)
        return sorted((bp.version for bp in self._by_key.values() if bp.name == canonical), key=_version_key)

    def list(self) -> list[Blueprint]: return [self._by_key[f"{name}@{version}"] for name, version in self._latest.items()]

    def search(self, query: str = "", category: str | None = None, tag: str | None = None) -> list[dict[str, Any]]:
        results = []
        for bp in self.list():
            if category and bp.category != category: continue
            if tag and tag not in bp.tags: continue
            haystack = " ".join([bp.name, bp.description, *bp.aliases, *bp.tags, bp.category]).lower()
            if query and query.lower() not in haystack: continue
            results.append(bp.summary())
        return sorted(results, key=lambda item: item["name"])


class BlueprintStore:
    """JSON-overlay persistence, mirrors MissionStore/GroupStore exactly: one file
    next to the config, atomically replaced, no migrations, no database."""

    def __init__(self, config_path: Path):
        self.path = config_path.with_suffix(".blueprints.json")
        self._data = self._load()

    def _load(self) -> dict[str, Any]:
        empty = {"history": {}, "applied": {}, "capabilities": {}}
        if not self.path.exists(): return empty
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
            for key in empty: data.setdefault(key, {})
            return data
        except (OSError, json.JSONDecodeError):
            return empty

    def _save(self) -> None: atomic_write(self.path, json.dumps(self._data, indent=2) + "\n")

    def record_run(self, project: str, blueprint: Blueprint, *, inputs: dict[str, Any], result: str,
                    changed: list[str], failed_step: str | None = None) -> dict[str, Any]:
        entry = {
            "id": _id("bpr"), "blueprint": blueprint.name, "stable_id": blueprint.stable_id, "version": blueprint.version,
            "applied_at": _now(), "result": result,
            "inputs": {key: value for key, value in inputs.items() if not _looks_sensitive(key)},
            "changed_steps": changed, "failed_step": failed_step,
        }
        self._data["history"].setdefault(project, []).append(entry)
        if result == "applied":
            self._data["applied"].setdefault(project, {})[blueprint.name] = {"version": blueprint.version, "applied_at": entry["applied_at"]}
            capabilities = set(self._data["capabilities"].get(project, []))
            capabilities.update(blueprint.resulting_capabilities)
            self._data["capabilities"][project] = sorted(capabilities)
        self._save()
        return entry

    def history(self, project: str) -> list[dict[str, Any]]: return list(self._data["history"].get(project, []))
    def applied(self, project: str) -> dict[str, Any]: return dict(self._data["applied"].get(project, {}))
    def capabilities(self, project: str) -> list[str]: return list(self._data["capabilities"].get(project, []))


def _resolve_inputs(blueprint: Blueprint, provided: dict[str, Any]) -> dict[str, Any]:
    resolved: dict[str, Any] = {}
    for name, spec in blueprint.inputs.items():
        if name in provided and provided[name] is not None: resolved[name] = provided[name]
        elif "default" in spec: resolved[name] = spec["default"]
        elif spec.get("required"): raise BlueprintError(f"blueprint {blueprint.name!r} requires input {name!r}")
        else: resolved[name] = None
    extra = set(provided) - set(blueprint.inputs)
    if extra: raise BlueprintError(f"blueprint {blueprint.name!r} does not accept input(s): {', '.join(sorted(extra))}")
    return resolved


def _render(value: Any, inputs: dict[str, Any]) -> Any:
    if isinstance(value, str):
        try: return value.format(**inputs)
        except KeyError as error: raise BlueprintError(f"template references unknown input {error}") from error
    if isinstance(value, dict): return {key: _render(item, inputs) for key, item in value.items()}
    if isinstance(value, list): return [_render(item, inputs) for item in value]
    return value


def _step_applies(step: BlueprintStep, inputs: dict[str, Any]) -> bool:
    return not step.when or all(inputs.get(key) == value for key, value in step.when.items())


def _conflicts(cloud: Any, blueprint: Blueprint, project: str | None) -> list[dict[str, Any]]:
    known = set(cloud.blueprints.capabilities(project)) if project else set()
    return [{"requires": capability, "reason": f"{project or 'this target'} does not currently have recorded capability {capability!r}"}
            for capability in blueprint.requires if capability not in known]


def plan(cloud: Any, blueprint: Blueprint, *, actor: str, project: str | None = None, inputs: dict[str, Any] | None = None) -> dict[str, Any]:
    resolved_inputs = _resolve_inputs(blueprint, inputs or {})
    steps = toposort(blueprint.steps)
    planned: list[dict[str, Any]] = []
    will_change = satisfied = skipped = unknown = 0
    for step in steps:
        if not _step_applies(step, resolved_inputs):
            planned.append({"id": step.id, "action": step.action, "status": "skipped", "summary": "condition not met"})
            skipped += 1; continue
        args = _render(step.args, resolved_inputs)
        definition = cloud.actions.get(step.action)
        if not definition.supports_dry_run:
            planned.append({"id": step.id, "action": step.action, "args": args, "status": "unknown",
                             "summary": "dry-run is not supported for this action; it will execute for real on apply"})
            unknown += 1; continue
        outcome = cloud.run(step.action, actor=actor, **{**args, "dry_run": True})
        if not outcome.ok:
            planned.append({"id": step.id, "action": step.action, "args": args, "status": "error",
                             "summary": outcome.error.message if outcome.error else "failed"})
            unknown += 1; continue
        changed = bool(isinstance(outcome.result, dict) and outcome.result.get("changed"))
        if changed: will_change += 1
        else: satisfied += 1
        planned.append({"id": step.id, "action": step.action, "args": args, "status": "will_change" if changed else "satisfied",
                         "summary": (outcome.result or {}).get("summary", "")})
    return {"blueprint": blueprint.name, "version": blueprint.version, "project": project, "steps": planned,
            "will_change": will_change, "satisfied": satisfied, "skipped": skipped, "unknown": unknown,
            "conflicts": _conflicts(cloud, blueprint, project)}


def apply(cloud: Any, blueprint: Blueprint, *, actor: str, project: str | None = None, inputs: dict[str, Any] | None = None) -> dict[str, Any]:
    resolved_inputs = _resolve_inputs(blueprint, inputs or {})
    steps = toposort(blueprint.steps)
    executed: list[dict[str, Any]] = []; changed_steps: list[str] = []
    for step in steps:
        if not _step_applies(step, resolved_inputs):
            executed.append({"id": step.id, "action": step.action, "status": "skipped"}); continue
        args = _render(step.args, resolved_inputs)
        definition = cloud.actions.get(step.action)
        confirmation = ({"level": definition.confirmation, "confirmed": True, "authorization_id": f"blueprint:{blueprint.name}:{step.id}:{time.time_ns()}"}
                         if definition.confirmation != "none" else None)
        outcome = cloud.run(step.action, actor=actor, confirmation=confirmation, **args)
        executed.append({"id": step.id, **outcome.compact()})
        if not outcome.ok:
            if project is not None:
                cloud.blueprints.record_run(project, blueprint, inputs=resolved_inputs, result="failed", changed=changed_steps, failed_step=step.id)
            raise ProcedureFailed(blueprint.name, step.id, outcome.error.code if outcome.error else "action.failed",
                                   outcome.error.message if outcome.error else "blueprint step failed")
        if isinstance(outcome.result, dict) and outcome.result.get("changed"): changed_steps.append(step.id)
    record = cloud.blueprints.record_run(project, blueprint, inputs=resolved_inputs, result="applied", changed=changed_steps) if project is not None else None
    return {"blueprint": blueprint.name, "version": blueprint.version, "project": project, "steps": executed,
            "changed": changed_steps, "changed_count": len(changed_steps), "history_entry": record}
