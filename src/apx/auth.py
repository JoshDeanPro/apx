# SPDX-License-Identifier: MIT
"""Authentication: who is calling. Kept strictly separate from authorization (policy.py):
what an authenticated principal may do is decided entirely by PolicyEngine, using only the
local actor-id -> role mapping -- an authentication method never grants authority itself.

The local path (LocalAuthProvider) is always available and requires no configuration; it is
what every existing bare `actor="..."` caller has always effectively used. Additional
providers (e.g. OpenPower, see auth_openpower.py) are opt-in and registered on AuthManager.
"""
from __future__ import annotations

from typing import Any, Protocol

from .axp import Actor, AuthContext
from .identity import ActorRegistry, parse_actor_id

# AXP's Principal primitive already exists as axp.Actor (id/kind/display_name, kind-validated
# against ACTOR_KINDS) -- re-exported under the name this layer's vocabulary uses, rather than
# introducing a second identity record that could drift from it.
Principal = Actor


class AuthenticationError(RuntimeError): pass


class AuthProvider(Protocol):
    name: str
    def authenticate(self, credentials: dict[str, Any]) -> AuthContext: ...


class LocalAuthProvider:
    """Always available. Represents *how* a local identity was established -- "local" never
    means "unauthenticated"; it means authentication_method="local_os"."""
    name = "local"

    def __init__(self, actors: ActorRegistry):
        self.actors = actors

    def authenticate(self, credentials: dict[str, Any]) -> AuthContext:
        principal_id = credentials.get("principal_id") or self.actors.resolve_default()
        return self.default_context(principal_id)

    def default_context(self, principal_id: str) -> AuthContext:
        try: kind, _ = parse_actor_id(principal_id)
        except ValueError: kind = "human"
        return AuthContext(principal_id=principal_id, principal_type=kind, authentication_method="local_os", issuer="local")


class AuthManager:
    """Selects and dispatches to configured AuthProviders. `local` is always present;
    others (e.g. `openpower`) are registered only when explicitly configured."""

    def __init__(self, config: dict[str, Any] | None, actors: ActorRegistry):
        self.config = config or {}
        self.actors = actors
        self.local = LocalAuthProvider(actors)
        self.providers: dict[str, Any] = {"local": self.local}
        self.allow_local_fallback = bool(self.config.get("allow_local_fallback", True))

    def register(self, name: str, provider: AuthProvider) -> None:
        self.providers[name] = provider

    def default_context(self, principal_id: str) -> AuthContext:
        """Used by cloud.execute() whenever a caller supplies no explicit AuthContext --
        i.e. every existing bare `actor=...` call, keeping that path fully backward compatible."""
        return self.local.default_context(principal_id)

    def authenticate(self, method: str, credentials: dict[str, Any]) -> AuthContext:
        provider = self.providers.get(method)
        if provider is None: raise AuthenticationError(f"unknown authentication method {method!r}; configured: {sorted(self.providers)}")
        return provider.authenticate(credentials)
