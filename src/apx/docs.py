# SPDX-License-Identifier: MIT
"""Generate human, AI, and machine documentation from APX's structured truth.

Nothing here is hand-duplicated: every section is rendered from Resources, Context,
roles/policy, and state already known to a APX instance. Output always passes
through the existing credential redaction before being returned.
"""
from __future__ import annotations

import json
from typing import Any

AUDIENCES = ("human", "ai", "machine")


def _project(cloud, name: str):
    if name not in cloud.projects: raise ValueError(f"unknown project {name!r}")
    return cloud.projects[name]


def _relevant_rules(cloud, project: str) -> list[dict[str, Any]]:
    rules=[]
    for role in cloud.policy.roles.values():
        for kind in ("allow","deny"):
            for rule in getattr(role,kind):
                scoped_projects=rule.scope.get("project")
                if scoped_projects is None or project in scoped_projects:
                    rules.append({"role":role.name,"effect":kind,"action":rule.action,"scope":rule.scope or None})
    return rules


def _locations(cloud, project) -> list[dict[str, Any]]:
    return [{"host":loc.host,"path":loc.path,"role":loc.role} for loc in project.locations]


def _human(cloud, project) -> str:
    lines=[f"# {project.name}",""]
    if project.description: lines+=[project.description,""]
    lines+=["## Where it runs",""]
    for loc in _locations(cloud,project): lines.append(f"- **{loc['role']}** on `{loc['host']}`: `{loc['path']}`")
    if project.services: lines+=["","## Services",*(f"- {s}" for s in project.services)]
    if project.domains: lines+=["","## Domains",*(f"- {d}" for d in project.domains)]
    context=project.context or {}
    if context.get("commands"): lines+=["","## Operating it",*(f"- `{name}`: `{cmd}`" for name,cmd in context["commands"].items())]
    if context.get("deployment"): lines+=["","## Deployment / recovery",*(f"- {k}: {v}" for k,v in context["deployment"].items())]
    credentials=[c.id for c in cloud.credentials.references.values() if c.groups and project.name in c.groups]
    if credentials: lines+=["","## Credentials required (references only, never values)",*(f"- {c}" for c in credentials)]
    rules=_relevant_rules(cloud,project.name)
    if rules: lines+=["","## Who can operate this project",*(f"- `{r['role']}` {r['effect']} `{r['action']}`" + (f" (scope: {r['scope']})" if r['scope'] else "") for r in rules)]
    return "\n".join(lines)+"\n"


def _ai(cloud, project) -> str:
    context=project.context or {}
    lines=[f"# {project.name} -- agent context",""]
    if context.get("architecture"): lines+=["## Architecture",*(f"- {a}" for a in context["architecture"]),""]
    if context.get("preferred_technologies"): lines+=["## Preferred technologies",*(f"- {t}" for t in context["preferred_technologies"]),""]
    avoid=context.get("avoid_technologies") or context.get("avoid")
    if avoid: lines+=["## Avoid",*(f"- {t}" for t in avoid),""]
    if context.get("conventions"): lines+=["## Conventions",*(f"- {c}" for c in context["conventions"]),""]
    rules=_relevant_rules(cloud,project.name)
    allow=[r for r in rules if r["effect"]=="allow"]; deny=[r for r in rules if r["effect"]=="deny"]
    lines+=["## What you may do here"]
    lines+=[f"- role `{r['role']}` may `{r['action']}`" + (f" (scope: {r['scope']})" if r["scope"] else "") for r in allow] or ["- (no roles configured; policy is currently open for every actor)"]
    if deny: lines+=["","## Explicitly denied",*(f"- role `{r['role']}` may NOT `{r['action']}`" for r in deny)]
    lines+=["","## Where production lives"]
    lines+=[f"- {loc['role']} on `{loc['host']}`: `{loc['path']}`" for loc in _locations(cloud,project) if loc["role"] in {"production","runs_on"}] or ["- (no production location declared)"]
    return "\n".join(lines)+"\n"


def _machine(cloud, project) -> str:
    def is_related(resource) -> bool:
        if resource.id==f"project:{project.name}": return True
        return resource.attributes.get("project")==project.name
    payload={
        "project":project.to_dict(),
        "locations":_locations(cloud,project),
        "context":project.context,
        "policy":_relevant_rules(cloud,project.name),
        "state":cloud.state.status(),
        "resources":[r.to_dict() for r in cloud.resources() if is_related(r)],
    }
    return json.dumps(cloud.credentials.redact(payload),indent=2,sort_keys=True)+"\n"


def generate(cloud, project_name: str, audience: str = "human") -> str:
    if audience not in AUDIENCES: raise ValueError(f"unknown audience {audience!r}; expected one of {AUDIENCES}")
    project=_project(cloud,project_name)
    renderer={"human":_human,"ai":_ai,"machine":_machine}[audience]
    return cloud.credentials.redact_text(renderer(cloud,project))


def _mission_human(cloud, snapshot: dict[str, Any]) -> str:
    mission=snapshot["mission"]; by_status=snapshot["tasks_by_status"]
    lines=[f"# Mission: {mission['title']}","",mission["objective"],"",f"Status: **{mission['status']}**",""]
    counted=sum(len(ids) for ids in by_status.values())
    verified=len(by_status.get("verified",()))
    lines+=[f"Progress: {verified} / {counted} Tasks verified",""]
    for status in ("active","blocked","completed","verified","proposed","ready","cancelled"):
        ids=by_status.get(status)
        if ids: lines+=[f"## {status.capitalize()}",*(f"- {i}" for i in ids),""]
    if snapshot["open_blockers"]: lines+=["## Blocked",*(f"- {b['description']} ({b['kind']})" for b in snapshot["open_blockers"]),""]
    return "\n".join(lines)+"\n"


def _mission_ai(cloud, snapshot: dict[str, Any]) -> str:
    mission=snapshot["mission"]; active=snapshot["active_task"]; nxt=snapshot["next_task"]
    lines=[f"# Mission: {mission['title']} -- agent handoff","",f"Objective: {mission['objective']}",f"Status: {mission['status']}",""]
    if mission["constraints"]: lines+=["## Constraints",*(f"- {c}" for c in mission["constraints"]),""]
    if mission["success_criteria"]: lines+=["## Success criteria",*(f"- {c}" for c in mission["success_criteria"]),""]
    lines+=["## Current Task"]
    lines+=[f"- {active['id']}: {active['title']} -- {active['reason']}"] if active else ["- (none active)"]
    lines+=["","## Next likely Task"]
    lines+=[f"- {nxt['id']}: {nxt['title']} -- {nxt['reason']}"] if nxt else ["- (none proposed/ready)"]
    if snapshot["findings"]: lines+=["","## Known findings",*(f"- [{f['category']}] {f['summary']}" for f in snapshot["findings"])]
    if snapshot["decisions"]: lines+=["","## Decisions",*(f"- {d['subject']}: {d['decision']} ({d['reason']})" for d in snapshot["decisions"])]
    if snapshot["open_blockers"]: lines+=["","## Blockers",*(f"- {b['description']}" for b in snapshot["open_blockers"])]
    if snapshot["recent_evidence"]: lines+=["","## Recent evidence",*(f"- {e['kind']}: {e['summary']}" for e in snapshot["recent_evidence"])]
    return "\n".join(lines)+"\n"


def _mission_machine(cloud, snapshot: dict[str, Any]) -> str:
    return json.dumps(cloud.credentials.redact(snapshot),indent=2,sort_keys=True)+"\n"


def generate_mission(cloud, mission_id: str, audience: str = "human") -> str:
    if audience not in AUDIENCES: raise ValueError(f"unknown audience {audience!r}; expected one of {AUDIENCES}")
    snapshot=cloud.missions.resume(mission_id)
    renderer={"human":_mission_human,"ai":_mission_ai,"machine":_mission_machine}[audience]
    return cloud.credentials.redact_text(renderer(cloud,snapshot))
