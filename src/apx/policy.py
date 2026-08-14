# SPDX-License-Identifier: MPL-2.0
"""Scoped allow/deny policy engine evaluated at the AXP execution path.

Explicit deny always wins. Absent any configured roles, the engine is a no-op
(allows everything) so existing configurations and callers are unaffected --
enforcement switches on only once a user actually declares `[[roles]]`.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

from .axp import PolicyDecision
from .identity import ActorRegistry


def scope_values(value: Any) -> tuple[str, ...]:
    """A scope dimension's allowed values, tolerant of a bare string.

    `tuple("palisbot")` silently explodes a string into single characters, which
    would make a rule that can never match instead of raising -- a scope dimension
    is always coerced to a tuple of whole values, never iterated character-by-character.
    """
    if isinstance(value, str): return (value,)
    return tuple(value)


def _match_action(pattern: str, action: str) -> bool:
    if pattern == "*": return True
    if pattern.endswith(".*"): return action.startswith(pattern[:-1])
    return pattern == action


def _match_scope(scope: dict[str, tuple[str, ...]], target: dict[str, Any], state: str) -> bool:
    for dimension, allowed in scope.items():
        if dimension == "state":
            if state not in allowed: return False
            continue
        if dimension == "host":
            # Two-host actions (file.copy/file.sync) carry source_host/destination_host,
            # not "host" -- a host-scoped rule must still see either endpoint, or a deny
            # scoped to a sensitive host would silently never apply to those actions.
            touched = {v for v in (target.get("host"), target.get("source_host"), target.get("destination_host")) if v is not None}
            if not touched or not (touched & set(allowed)): return False
            continue
        value = target.get(dimension)
        if value is None or value not in allowed: return False
    return True


@dataclass(frozen=True)
class ScopedRule:
    action: str
    scope: dict[str, tuple[str, ...]] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]: return asdict(self)

    @classmethod
    def from_config(cls, value: dict[str, Any]) -> "ScopedRule":
        scope = {dimension: scope_values(values) for dimension, values in value.get("scope", {}).items()}
        return cls(action=value["action"], scope=scope)


@dataclass(frozen=True)
class RolePolicy:
    name: str
    allow: tuple[ScopedRule, ...] = ()
    deny: tuple[ScopedRule, ...] = ()

    @classmethod
    def from_config(cls, value: dict[str, Any]) -> "RolePolicy":
        return cls(
            name=value["name"],
            allow=tuple(ScopedRule.from_config(rule) for rule in value.get("allow", ())),
            deny=tuple(ScopedRule.from_config(rule) for rule in value.get("deny", ())),
        )


class PolicyEngine:
    def __init__(self, roles: dict[str, RolePolicy] | None = None, actors: ActorRegistry | None = None):
        self.roles = roles or {}
        self.actors = actors or ActorRegistry()

    @classmethod
    def from_config(cls, raw: list[dict[str, Any]], actors: ActorRegistry) -> "PolicyEngine":
        roles = {item["name"]: RolePolicy.from_config(item) for item in raw}
        return cls(roles, actors)

    @property
    def enabled(self) -> bool:
        """False until any [[roles]] are configured -- keeps unconfigured deployments open."""
        return bool(self.roles)

    def evaluate(self, actor_id: str, action: str, target: dict[str, Any] | None = None, state: str = "normal", extra_allow: tuple[ScopedRule, ...] = ()) -> PolicyDecision:
        """extra_allow (e.g. Mission-scoped temporary grants) is checked only after static
        allow/deny -- it can never override an explicit static deny, and is ignored entirely
        once any static deny already matched."""
        target = target or {}
        if not self.enabled:
            return PolicyDecision(True, actor_id, action, "policy not configured", None)
        role_names = self.actors.roles_for(actor_id)
        roles = [self.roles[name] for name in role_names if name in self.roles]
        for role in roles:
            for rule in role.deny:
                if _match_action(rule.action, action) and _match_scope(rule.scope, target, state):
                    return PolicyDecision(False, actor_id, action, f"denied by role {role.name!r} (explicit deny: {rule.action})", rule.scope or None)
        for role in roles:
            for rule in role.allow:
                if _match_action(rule.action, action) and _match_scope(rule.scope, target, state):
                    return PolicyDecision(True, actor_id, action, f"allowed by role {role.name!r} ({rule.action})", rule.scope or None)
        for rule in extra_allow:
            if _match_action(rule.action, action) and _match_scope(rule.scope, target, state):
                return PolicyDecision(True, actor_id, action, f"allowed by mission-scoped grant ({rule.action})", rule.scope or None)
        return PolicyDecision(False, actor_id, action, "No applicable allow policy.", None)

    def explain(self, actor_id: str, action: str, target: dict[str, Any] | None = None, state: str = "normal", extra_allow: tuple[ScopedRule, ...] = ()) -> PolicyDecision:
        return self.evaluate(actor_id, action, target, state, extra_allow)

    def roles_for(self, actor_id: str) -> tuple[str, ...]:
        return self.actors.roles_for(actor_id)

    def might_allow(self, actor_id: str, action: str, extra_allow: tuple[ScopedRule, ...] = ()) -> bool:
        """Coarse, scope-agnostic pre-check for convenience UIs and discovery (e.g. MCP tool
        listing, APX.discover()). Not authoritative -- evaluate() is, and still runs at
        invocation time. `extra_allow` (Mission grants, standalone Grants) is considered
        the same way static role.allow rules are -- delegated authority must be visible
        during discovery, not just enforced silently at execute() time, or a UI/agent
        would never learn it can use a capability a Grant just gave it."""
        if not self.enabled: return True
        role_names = self.actors.roles_for(actor_id)
        roles = [self.roles[name] for name in role_names if name in self.roles]
        for role in roles:
            for rule in role.deny:
                if _match_action(rule.action, action) and not rule.scope: return False
        for role in roles:
            for rule in role.allow:
                if _match_action(rule.action, action): return True
        for rule in extra_allow:
            if _match_action(rule.action, action): return True
        return False
