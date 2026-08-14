# SPDX-License-Identifier: MPL-2.0
"""Grants: standalone, independently-expiring, revocable delegated authority.

A Grant is deliberately distinct from MissionStore's `temporary_permissions`
(missions.py) -- a Mission grant only exists for the lifetime of its parent
Mission and has no id, no independent expiry, and no revoke primitive. A Grant
here is a first-class resource: it has its own id, its own `expires_at`, can be
revoked directly, and can scope by resource reference (see axp.resource_ref) as
well as arbitrary constraints. Both feed PolicyEngine.evaluate()'s extra_allow --
delegated authority is delegated authority, whichever store it lives in.

Storage mirrors MissionStore/BlueprintStore: one JSON overlay file next to the
config, atomically replaced, no migrations, no database.
"""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

from .files import atomic_write


class GrantError(RuntimeError): pass


def _now() -> str: return datetime.now(timezone.utc).isoformat()
def _id() -> str: return f"grant-{uuid4().hex[:8]}"


@dataclass(frozen=True)
class Grant:
    id: str
    subject: str  # actor id this authority is delegated to
    issued_by: str  # actor id that issued it (must itself hold every action pattern granted)
    actions: tuple[str, ...]  # exact action names or "namespace.*" patterns
    resources: tuple[str, ...] = ()  # apx:// resource refs this grant is scoped to; empty = any resource
    constraints: dict[str, Any] = field(default_factory=dict)  # matched like ScopedRule.scope
    reason: str = ""
    issued_at: str = field(default_factory=_now)
    expires_at: str | None = None
    revoked_at: str | None = None
    revoked_by: str | None = None

    def __post_init__(self) -> None:
        if not self.subject: raise ValueError("a grant requires a subject")
        if not self.issued_by: raise ValueError("a grant requires an issuer")
        if not self.actions: raise ValueError(f"grant {self.id!r} must delegate at least one action")

    def active(self, *, now: str | None = None) -> bool:
        if self.revoked_at is not None: return False
        if self.expires_at is None: return True
        # Parsed, not compared as raw strings: two ISO-8601 timestamps in different
        # UTC offsets are not correctly orderable lexicographically.
        current = datetime.fromisoformat(now) if now else datetime.now(timezone.utc)
        return current < datetime.fromisoformat(self.expires_at)

    def to_dict(self) -> dict[str, Any]: return {**asdict(self), "active": self.active()}


class GrantStore:
    def __init__(self, config_path: Path):
        self.path = config_path.with_suffix(".grants.json")
        self._data = self._load()

    def _load(self) -> dict[str, Any]:
        empty = {"grants": {}}
        if not self.path.exists(): return empty
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
            for key in empty: data.setdefault(key, {})
            return data
        except (OSError, json.JSONDecodeError):
            return empty

    def _save(self) -> None: atomic_write(self.path, json.dumps(self._data, indent=2) + "\n")

    def issue(self, subject: str, issued_by: str, actions: tuple[str, ...], *, resources: tuple[str, ...] = (),
              constraints: dict[str, Any] | None = None, reason: str = "", expires_at: str | None = None) -> Grant:
        grant = Grant(_id(), subject, issued_by, tuple(actions), resources=tuple(resources),
                       constraints=dict(constraints or {}), reason=reason, expires_at=expires_at)
        self._data["grants"][grant.id] = asdict(grant)
        self._save()
        return grant

    def get(self, grant_id: str) -> Grant:
        try: return Grant(**self._data["grants"][grant_id])
        except KeyError as error: raise GrantError(f"unknown grant {grant_id!r}") from error

    def list(self, *, subject: str | None = None, include_expired: bool = False) -> list[Grant]:
        values = (Grant(**raw) for raw in self._data["grants"].values())
        if subject is not None: values = (g for g in values if g.subject == subject)
        if not include_expired: values = (g for g in values if g.active())
        return sorted(values, key=lambda g: g.issued_at)

    def active_for(self, subject: str) -> list[Grant]: return self.list(subject=subject)

    def revoke(self, grant_id: str, *, revoked_by: str | None = None) -> Grant:
        grant = self.get(grant_id)
        if grant.revoked_at is not None: raise GrantError(f"grant {grant_id!r} is already revoked")
        revoked = Grant(**{**asdict(grant), "revoked_at": _now(), "revoked_by": revoked_by})
        self._data["grants"][grant_id] = asdict(revoked)
        self._save()
        return revoked
