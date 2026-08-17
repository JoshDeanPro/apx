# SPDX-License-Identifier: MIT
"""Project -> Mission -> Tasks -> AXP Actions -> Evidence.

AXP gives an actor actions. Missions make sure those actions have a purpose: every
Task exists *because* of a Mission (see `reason`), and a Mission is only "verified"
once its evidence has been checked against its own success criteria -- not merely
because an actor believes the work is done.

Storage mirrors GroupStore/StateStore exactly: one JSON overlay file next to the
config, atomically replaced under a small advisory lock, no migrations or database.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4
from .files import atomic_write

STATUSES = ("proposed", "ready", "active", "blocked", "completed", "verified", "cancelled")
FINDING_CATEGORIES = ("informational", "relevant", "blocker", "security", "future_work")
SCOPE_CHANGE_STATUSES = ("pending", "approved", "denied", "modified")
ENDED_MISSION_STATUSES = ("completed", "verified", "cancelled")
GRANTING_MISSION_STATUSES = ("active", "blocked")

MISSION_TEMPLATES = {
    "bug_fix": {"description": "Diagnose and repair a defect.", "steps": ["reproduce", "diagnose", "implement", "test", "verify", "deploy if applicable", "verify target environment"]},
    "deployment": {"description": "Ship a change to a running environment.", "steps": ["prepare release", "deploy", "smoke test", "verify production health"]},
    "new_feature": {"description": "Add new capability.", "steps": ["design", "implement", "test", "document", "verify"]},
    "cleanup": {"description": "Remove or simplify existing work without changing behavior.", "steps": ["inventory", "remove/simplify", "test", "verify no regression"]},
    "migration": {"description": "Move or transform data/infrastructure.", "steps": ["plan", "dry run", "migrate", "verify integrity", "decommission old path"]},
    "security_review": {"description": "Assess and address security posture.", "steps": ["inventory attack surface", "assess", "remediate", "verify"]},
    "incident_response": {"description": "Respond to an active incident.", "steps": ["triage", "contain", "diagnose", "remediate", "verify recovery", "postmortem"]},
    "backup_recovery": {"description": "Verify or restore backup integrity.", "steps": ["identify backup", "test restore", "verify integrity", "document recovery"]},
    "new_project": {"description": "Stand up a new project.", "steps": ["scaffold", "configure", "initial deployment", "verify"]},
}


class MissionError(RuntimeError): pass


def _now() -> str: return datetime.now(timezone.utc).isoformat()
def _id(prefix: str) -> str: return f"{prefix}-{uuid4().hex[:8]}"


def templates(cloud) -> dict[str, Any]:
    merged = dict(MISSION_TEMPLATES)
    for item in cloud.config.get("mission_templates", ()):
        merged[item["name"]] = {"description": item.get("description", ""), "steps": list(item.get("steps", ()))}
    return merged


class MissionStore:
    def __init__(self, config_path: Path):
        self.path = config_path.with_suffix(".missions.json")
        self._data = self._load()

    def _load(self) -> dict[str, Any]:
        empty = {"missions": {}, "tasks": {}, "findings": {}, "decisions": {}, "blockers": {}, "evidence": {}, "scope_changes": {}}
        if not self.path.exists(): return empty
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
            for key in empty: data.setdefault(key, {})
            return data
        except (OSError, json.JSONDecodeError):
            return empty

    def _save(self) -> None: atomic_write(self.path,json.dumps(self._data, indent=2) + "\n")

    # ---- Mission ----

    def create_mission(self, project: str, title: str, objective: str, *, description: str = "", owner: str | None = None,
                        assigned_agents: list[str] | None = None, priority: str = "normal", scope: str = "",
                        constraints: list[str] | None = None, success_criteria: list[str] | None = None,
                        related_resources: list[str] | None = None) -> dict[str, Any]:
        mission = {
            "id": _id("ms"), "project": project, "title": title, "objective": objective, "description": description,
            "owner": owner, "assigned_agents": assigned_agents or [], "status": "proposed", "priority": priority,
            "scope": scope, "constraints": constraints or [], "success_criteria": success_criteria or [],
            "related_resources": related_resources or [], "temporary_permissions": [],
            "created_at": _now(), "started_at": None, "completed_at": None, "verified_at": None,
            "verification": None, "summary": "",
        }
        self._data["missions"][mission["id"]] = mission; self._save()
        return mission

    def get_mission(self, mission_id: str) -> dict[str, Any]:
        try: return self._data["missions"][mission_id]
        except KeyError as error: raise MissionError(f"unknown mission {mission_id!r}") from error

    def list_missions(self, project: str | None = None, status: str | None = None) -> list[dict[str, Any]]:
        values = self._data["missions"].values()
        if project: values = [m for m in values if m["project"] == project]
        if status: values = [m for m in values if m["status"] == status]
        return sorted(values, key=lambda m: m["created_at"])

    def _blockers_for(self, *, mission: str | None = None, task: str | None = None, unresolved_only: bool = True) -> list[dict[str, Any]]:
        values = self._data["blockers"].values()
        if mission is not None: values = [b for b in values if b["mission"] == mission]
        if task is not None: values = [b for b in values if b.get("task") == task]
        if unresolved_only: values = [b for b in values if b["resolved_at"] is None]
        return list(values)

    def set_mission_status(self, mission_id: str, status: str, *, reason: str = "", actor: str | None = None) -> dict[str, Any]:
        if status not in STATUSES: raise MissionError(f"invalid mission status {status!r}")
        mission = self.get_mission(mission_id)
        if status == "completed" and self._blockers_for(mission=mission_id):
            raise MissionError(f"mission {mission_id!r} has unresolved blockers; resolve them before completing")
        mission["status"] = status
        if status == "active" and not mission["started_at"]: mission["started_at"] = _now()
        if status == "completed": mission["completed_at"] = _now()
        if status in {"blocked", "cancelled"}: mission["summary"] = reason or mission["summary"]
        self._save()
        return mission

    def verify_mission(self, mission_id: str, *, criteria_met: list[str] | None = None, actor: str | None = None) -> dict[str, Any]:
        mission = self.get_mission(mission_id)
        required = set(mission["success_criteria"]); met = set(criteria_met or [])
        verified = required.issubset(met) if required else True
        mission["verification"] = {"verified": verified, "criteria_met": sorted(met), "missing": sorted(required - met), "at": _now(), "by": actor}
        if verified: mission["status"] = "verified"; mission["verified_at"] = _now()
        self._save()
        return mission

    def grant_permission(self, mission_id: str, actor: str, action: str, scope: dict[str, list[str]] | None = None) -> dict[str, Any]:
        mission = self.get_mission(mission_id)
        grant = {"actor": actor, "action": action, "scope": scope or {}}
        mission["temporary_permissions"].append(grant); self._save()
        return grant

    def active_grants(self, actor_id: str) -> list[dict[str, Any]]:
        grants = []
        for mission in self._data["missions"].values():
            if mission["status"] not in GRANTING_MISSION_STATUSES: continue
            grants.extend(g for g in mission["temporary_permissions"] if g["actor"] == actor_id)
        return grants

    # ---- Task ----

    def create_task(self, mission_id: str, title: str, reason: str, *, objective: str = "", assigned_actor: str | None = None,
                     dependencies: list[str] | None = None, related_resources: list[str] | None = None,
                     required_actions: list[str] | None = None, acceptance_criteria: list[str] | None = None,
                     recommended_prompts: list[str] | None = None) -> dict[str, Any]:
        self.get_mission(mission_id)  # validates existence
        task = {
            "id": _id("tk"), "mission": mission_id, "title": title, "objective": objective, "reason": reason,
            "status": "proposed", "assigned_actor": assigned_actor, "claimed_by": None,
            "dependencies": dependencies or [], "related_resources": related_resources or [],
            "required_actions": required_actions or [], "acceptance_criteria": acceptance_criteria or [],
            "recommended_prompts": recommended_prompts or [], "created_at": _now(),
            "started_at": None, "completed_at": None, "verified_at": None, "verification": None,
        }
        self._data["tasks"][task["id"]] = task; self._save()
        return task

    def propose_tasks(self, mission_id: str, proposals: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """An agent's derived plan, stored verbatim -- APX does not invent Tasks itself."""
        return [self.create_task(mission_id, **proposal) for proposal in proposals]

    def get_task(self, task_id: str) -> dict[str, Any]:
        try: return self._data["tasks"][task_id]
        except KeyError as error: raise MissionError(f"unknown task {task_id!r}") from error

    def list_tasks(self, mission: str | None = None, status: str | None = None, actor: str | None = None) -> list[dict[str, Any]]:
        values = self._data["tasks"].values()
        if mission: values = [t for t in values if t["mission"] == mission]
        if status: values = [t for t in values if t["status"] == status]
        if actor: values = [t for t in values if t["assigned_actor"] == actor or t["claimed_by"] == actor]
        return sorted(values, key=lambda t: t["created_at"])

    def set_task_status(self, task_id: str, status: str, *, reason: str = "", actor: str | None = None) -> dict[str, Any]:
        if status not in STATUSES: raise MissionError(f"invalid task status {status!r}")
        task = self.get_task(task_id)
        if status == "active":
            unmet = [d for d in task["dependencies"] if self.get_task(d)["status"] not in {"completed", "verified"}]
            if unmet: raise MissionError(f"task {task_id!r} has unmet dependencies: {unmet}")
        if status == "completed" and self._blockers_for(task=task_id):
            raise MissionError(f"task {task_id!r} has unresolved blockers; resolve them before completing")
        task["status"] = status
        if status == "active" and not task["started_at"]: task["started_at"] = _now()
        if status == "completed": task["completed_at"] = _now()
        self._save()
        return task

    def verify_task(self, task_id: str, *, criteria_met: list[str] | None = None, actor: str | None = None) -> dict[str, Any]:
        task = self.get_task(task_id)
        required = set(task["acceptance_criteria"]); met = set(criteria_met or [])
        verified = required.issubset(met) if required else True
        task["verification"] = {"verified": verified, "criteria_met": sorted(met), "missing": sorted(required - met), "at": _now(), "by": actor}
        if verified: task["status"] = "verified"; task["verified_at"] = _now()
        self._save()
        return task

    def claim_task(self, task_id: str, actor: str) -> dict[str, Any]:
        if not actor: raise MissionError("an actor is required to claim a task")
        task = self.get_task(task_id)
        if task["claimed_by"] and task["claimed_by"] != actor:
            raise MissionError(f"task {task_id!r} is already claimed by {task['claimed_by']!r}")
        task["claimed_by"] = actor; self._save()
        return task

    def release_task(self, task_id: str, actor: str) -> dict[str, Any]:
        if not actor: raise MissionError("an actor is required to release a task")
        task = self.get_task(task_id)
        if task["claimed_by"] and task["claimed_by"] != actor:
            raise MissionError(f"task {task_id!r} is claimed by {task['claimed_by']!r}, not {actor!r}")
        task["claimed_by"] = None; self._save()
        return task

    def detect_conflicts(self, task_id: str) -> list[dict[str, Any]]:
        task = self.get_task(task_id); resources = set(task["related_resources"])
        conflicts = []
        for other in self._data["tasks"].values():
            if other["id"] == task_id or other["status"] not in {"active", "blocked"}: continue
            overlap = resources & set(other["related_resources"])
            if overlap: conflicts.append({"task": other["id"], "mission": other["mission"], "overlapping_resources": sorted(overlap)})
        return conflicts

    # ---- Findings / Decisions / Blockers / Evidence ----

    def add_finding(self, mission_id: str, summary: str, *, task: str | None = None, category: str = "informational", reported_by: str | None = None) -> dict[str, Any]:
        if category not in FINDING_CATEGORIES: raise MissionError(f"invalid finding category {category!r}")
        self.get_mission(mission_id)
        finding = {"id": _id("fd"), "mission": mission_id, "task": task, "summary": summary, "category": category, "reported_by": reported_by, "created_at": _now()}
        self._data["findings"][finding["id"]] = finding; self._save()
        return finding

    def list_findings(self, mission: str | None = None) -> list[dict[str, Any]]:
        values = self._data["findings"].values()
        return sorted([f for f in values if mission is None or f["mission"] == mission], key=lambda f: f["created_at"])

    def record_decision(self, subject: str, decision: str, reason: str, *, actor: str | None = None, mission: str | None = None,
                         project: str | None = None, affected_resources: list[str] | None = None, evidence: str | None = None) -> dict[str, Any]:
        record = {"id": _id("dc"), "subject": subject, "decision": decision, "reason": reason, "actor": actor,
                   "mission": mission, "project": project, "affected_resources": affected_resources or [], "evidence": evidence, "created_at": _now()}
        self._data["decisions"][record["id"]] = record; self._save()
        return record

    def list_decisions(self, mission: str | None = None, project: str | None = None) -> list[dict[str, Any]]:
        values = self._data["decisions"].values()
        if mission: values = [d for d in values if d["mission"] == mission]
        if project: values = [d for d in values if d["project"] == project]
        return sorted(values, key=lambda d: d["created_at"])

    def add_blocker(self, mission_id: str, kind: str, description: str, *, task: str | None = None) -> dict[str, Any]:
        self.get_mission(mission_id)
        if task: self.get_task(task)  # validate before mutating -- raises MissionError, not a raw KeyError, on a bad id
        blocker = {"id": _id("bl"), "mission": mission_id, "task": task, "kind": kind, "description": description,
                   "created_at": _now(), "resolved_at": None, "resolved_by": None, "resolution": None}
        self._data["blockers"][blocker["id"]] = blocker
        if task: self._data["tasks"][task]["status"] = "blocked"
        else: self._data["missions"][mission_id]["status"] = "blocked"
        self._save()
        return blocker

    def resolve_blocker(self, blocker_id: str, resolution: str, *, actor: str | None = None) -> dict[str, Any]:
        try: blocker = self._data["blockers"][blocker_id]
        except KeyError as error: raise MissionError(f"unknown blocker {blocker_id!r}") from error
        blocker["resolved_at"] = _now(); blocker["resolved_by"] = actor; blocker["resolution"] = resolution
        self._save()
        return blocker

    def list_blockers(self, mission: str | None = None, task: str | None = None, unresolved_only: bool = False) -> list[dict[str, Any]]:
        return self._blockers_for(mission=mission, task=task, unresolved_only=unresolved_only) if (mission or task) else \
            [b for b in self._data["blockers"].values() if not unresolved_only or b["resolved_at"] is None]

    def attach_evidence(self, task_id: str, kind: str, summary: str, *, reference: str | None = None, attached_by: str | None = None) -> dict[str, Any]:
        self.get_task(task_id)
        evidence = {"id": _id("ev"), "task": task_id, "kind": kind, "summary": summary, "reference": reference, "attached_by": attached_by, "created_at": _now()}
        self._data["evidence"][evidence["id"]] = evidence; self._save()
        return evidence

    def list_evidence(self, task: str | None = None) -> list[dict[str, Any]]:
        values = self._data["evidence"].values()
        return sorted([e for e in values if task is None or e["task"] == task], key=lambda e: e["created_at"])

    # ---- Scope change ----

    def request_scope_change(self, mission_id: str, requested_by: str, reason: str, impact: str, *, affected_resources: list[str] | None = None) -> dict[str, Any]:
        self.get_mission(mission_id)
        request = {"id": _id("sc"), "mission": mission_id, "requested_by": requested_by, "reason": reason, "impact": impact,
                   "affected_resources": affected_resources or [], "status": "pending", "resolved_by": None, "resolution": None, "created_at": _now()}
        self._data["scope_changes"][request["id"]] = request; self._save()
        return request

    def resolve_scope_change(self, request_id: str, status: str, *, resolution: str = "", actor: str | None = None) -> dict[str, Any]:
        if status not in {"approved", "denied", "modified"}: raise MissionError(f"invalid scope change resolution {status!r}")
        try: request = self._data["scope_changes"][request_id]
        except KeyError as error: raise MissionError(f"unknown scope change request {request_id!r}") from error
        request["status"] = status; request["resolved_by"] = actor; request["resolution"] = resolution
        self._save()
        return request

    def list_scope_changes(self, mission: str | None = None) -> list[dict[str, Any]]:
        values = self._data["scope_changes"].values()
        return sorted([s for s in values if mission is None or s["mission"] == mission], key=lambda s: s["created_at"])

    # ---- Work context / handoff ----

    def current_for_actor(self, actor_id: str) -> dict[str, Any] | None:
        candidates = [t for t in self._data["tasks"].values() if t["status"] in {"active", "blocked"} and (t["claimed_by"] == actor_id or t["assigned_actor"] == actor_id)]
        if not candidates: return None
        return sorted(candidates, key=lambda t: t["started_at"] or t["created_at"], reverse=True)[0]

    def resume(self, mission_id: str) -> dict[str, Any]:
        mission = self.get_mission(mission_id)
        tasks = self.list_tasks(mission=mission_id)
        by_status: dict[str, list[dict[str, Any]]] = {}
        for task in tasks: by_status.setdefault(task["status"], []).append(task)
        active = by_status.get("active", [])
        next_task = next((t for t in sorted(tasks, key=lambda t: t["created_at"]) if t["status"] in {"proposed", "ready"}), None)
        return {
            "mission": mission, "tasks_by_status": {status: [t["id"] for t in items] for status, items in by_status.items()},
            "active_task": active[0] if active else None,
            "findings": self.list_findings(mission_id), "decisions": self.list_decisions(mission=mission_id),
            "open_blockers": self.list_blockers(mission=mission_id, unresolved_only=True),
            "recent_evidence": [e for t in tasks for e in self.list_evidence(t["id"])][-10:],
            "next_task": next_task,
        }
