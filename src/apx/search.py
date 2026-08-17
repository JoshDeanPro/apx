# SPDX-License-Identifier: MIT
"""Deterministic local search over already-known APX state.

No embeddings, no vector database, no AI call -- APX already knows its own hosts,
projects, actions, blueprints, connections, and grants; a query should look them up
directly instead of spending a model call rediscovering state APX already has.
replacement for a fast deterministic index existing first.
"""
from __future__ import annotations

from typing import Any

_EXACT, _STARTSWITH, _CONTAINS_PRIMARY, _CONTAINS_SECONDARY = 100, 70, 50, 20


def _score(query: str, primary: str, secondary: tuple[str, ...]) -> int:
    primary_l = primary.lower()
    if primary_l == query: return _EXACT
    if primary_l.startswith(query): return _STARTSWITH
    if query in primary_l: return _CONTAINS_PRIMARY
    if any(query in (value or "").lower() for value in secondary): return _CONTAINS_SECONDARY
    return 0


def _entry(kind: str, id: str, title: str, description: str, score: int, **extra: Any) -> dict[str, Any]:
    return {"kind": kind, "id": id, "title": title, "description": description, "score": score, **extra}


def query(cloud: Any, text: str, *, kinds: tuple[str, ...] = (), limit: int = 20) -> list[dict[str, Any]]:
    q = text.strip().lower()
    if not q: return []
    results: list[dict[str, Any]] = []

    def wanted(kind: str) -> bool: return not kinds or kind in kinds

    if wanted("node"):
        for host in cloud.hosts.values():
            score = _score(q, host.name, (host.transport, host.target or "", *host.tags, *host.groups))
            if score: results.append(_entry("node", host.name, host.name, f"{host.transport} host", score, tags=list(host.tags)))

    if wanted("project"):
        for project in cloud.projects.values():
            score = _score(q, project.name, (project.description, *project.tags))
            if score: results.append(_entry("project", project.name, project.name, project.description, score, tags=list(project.tags)))

    if wanted("action"):
        for action in cloud.actions.list():
            score = _score(q, action.name, (action.description, *action.tags))
            if score: results.append(_entry("action", action.name, action.name, action.description, score, risk=action._risk()))

    if wanted("blueprint"):
        for blueprint in cloud.blueprint_registry.list():
            score = _score(q, blueprint.name, (blueprint.description, blueprint.category, *blueprint.tags, *blueprint.aliases))
            if score: results.append(_entry("blueprint", blueprint.name, blueprint.name, blueprint.description, score, category=blueprint.category))

    if wanted("connection"):
        for connection in cloud.connections:
            score = _score(q, connection.id, (connection.adapter, connection.resource or ""))
            if score: results.append(_entry("connection", connection.id, connection.id, connection.adapter, score, adapter=connection.adapter))

    if wanted("grant"):
        for grant in cloud.grants.list(include_expired=False):
            haystack = (grant.subject, grant.issued_by, grant.reason, *grant.actions)
            score = _score(q, grant.subject, haystack)
            if score: results.append(_entry("grant", grant.id, f"{grant.subject} ({', '.join(grant.actions)})", grant.reason, score, subject=grant.subject))

    results.sort(key=lambda item: item["score"], reverse=True)
    return results[:max(1, limit)]
