"""Optional OpenPower identity adapter. Never imported/required unless [auth.openpower] is
configured -- AXP Core has no dependency on this module or on OpenPower being reachable.

OpenPower can authenticate who an actor is. AXP still decides locally what that actor may
do (policy.py) -- this module only ever produces an AuthContext, never a permission.

JWT (RFC 7519) verification is implemented here using only stdlib primitives (hmac/hashlib/
base64/json) -- HS256 (shared-secret HMAC) only. This is verification of an established,
documented protocol using vetted stdlib crypto primitives, not an invented signature scheme.
Asymmetric verification (RS256/EdDSA, needed to avoid a shared secret in production) would
require a real crypto dependency and is intentionally left for a later milestone.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import time
import urllib.error
import urllib.request
from dataclasses import replace
from typing import Any, Callable

from .auth import AuthenticationError
from .axp import AuthContext


def _b64url_decode(segment: str) -> bytes:
    return base64.urlsafe_b64decode(segment + "=" * (-len(segment) % 4))


def verify_jwt_hs256(token: str, secret: str, *, issuer: str | None = None, audience: str | None = None, leeway: int = 30) -> dict[str, Any]:
    """Minimal, stdlib-only HS256 JWT verifier. Rejects alg != HS256 (explicitly refuses the
    classic `alg: none` bypass), bad signatures, expired/not-yet-valid tokens, and wrong
    issuer/audience. Returns the verified claims dict."""
    try:
        header_b64, payload_b64, signature_b64 = token.split(".")
    except ValueError as error:
        raise AuthenticationError("malformed token") from error
    try:
        header = json.loads(_b64url_decode(header_b64))
        claims = json.loads(_b64url_decode(payload_b64))
        signature = _b64url_decode(signature_b64)
    except (ValueError, UnicodeDecodeError) as error:
        raise AuthenticationError(f"malformed token: {error}") from error
    if header.get("alg") != "HS256":
        raise AuthenticationError(f"rejected token algorithm {header.get('alg')!r}; only HS256 is accepted")
    expected=hmac.new(secret.encode(),f"{header_b64}.{payload_b64}".encode(),hashlib.sha256).digest()
    if not hmac.compare_digest(expected,signature):
        raise AuthenticationError("invalid token signature")
    now=time.time()
    exp=claims.get("exp")
    if exp is not None and now > exp+leeway: raise AuthenticationError("token has expired")
    nbf=claims.get("nbf")
    if nbf is not None and now < nbf-leeway: raise AuthenticationError("token is not yet valid")
    if issuer is not None and claims.get("iss") != issuer: raise AuthenticationError(f"unexpected issuer {claims.get('iss')!r}")
    if audience is not None:
        aud=claims.get("aud"); aud_values=aud if isinstance(aud,list) else [aud]
        if audience not in aud_values: raise AuthenticationError(f"unexpected audience {aud!r}")
    if "sub" not in claims: raise AuthenticationError("token missing required 'sub' claim")
    return claims


class OpenPowerAuthProvider:
    """Validates OpenPower-issued identity assertions (JWTs). The revocation-status check is
    the only network-dependent step -- signature/claims verification is fully local. See
    authenticate() for the offline/cache behavior when that check can't reach OpenPower."""
    name = "openpower"

    def __init__(self, base_url: str, shared_secret_env: str, issuer: str = "openpower.one", audience: str = "axp",
                 request: Callable[[str, str], dict[str, Any]] | None = None, allow_offline: bool = True):
        self.base_url = base_url.rstrip("/"); self.shared_secret_env = shared_secret_env
        self.issuer = issuer; self.audience = audience
        self._request = request or self._http_request
        self.allow_offline = allow_offline
        self._cache: dict[str, AuthContext] = {}

    def _secret(self) -> str:
        secret = os.environ.get(self.shared_secret_env, "")
        if not secret: raise AuthenticationError(f"OpenPower shared secret environment variable {self.shared_secret_env!r} is not set")
        return secret

    def _http_request(self, method: str, path: str) -> dict[str, Any]:
        request = urllib.request.Request(f"{self.base_url}{path}", method=method)
        with urllib.request.urlopen(request, timeout=10) as response: return json.loads(response.read() or b"{}")

    def authenticate(self, credentials: dict[str, Any]) -> AuthContext:
        token = credentials.get("token")
        if not token: raise AuthenticationError("OpenPower authentication requires a 'token'")
        claims = verify_jwt_hs256(token, self._secret(), issuer=self.issuer, audience=self.audience)
        principal_id = claims["sub"]; principal_type = claims.get("principal_type", "agent")
        expires_at = time.strftime("%Y-%m-%dT%H:%M:%S+00:00", time.gmtime(claims["exp"])) if claims.get("exp") else None
        try:
            status = self._request("GET", f"/v1/agents/{principal_id}/status")
        except Exception as error:  # network unreachable, DNS failure, timeout, etc.
            if not self.allow_offline: raise AuthenticationError(f"OpenPower is unreachable and offline fallback is disabled: {error}") from error
            cached = self._cache.get(principal_id)
            if cached and (cached.expires_at is None or cached.expires_at > time.strftime("%Y-%m-%dT%H:%M:%S+00:00", time.gmtime())):
                # Never silently report a fresh online validation when none occurred.
                return replace(cached, authentication_method="cached_openpower")
            return AuthContext(principal_id=principal_id, principal_type=principal_type, authentication_method="openpower_offline", issuer="openpower", expires_at=expires_at)
        if status.get("revoked"): raise AuthenticationError(f"principal {principal_id!r} has a revoked OpenPower credential")
        context = AuthContext(principal_id=principal_id, principal_type=principal_type, authentication_method="openpower", issuer="openpower", expires_at=expires_at)
        self._cache[principal_id] = context
        return context

    def link_human(self, local_actor_id: str, openpower_subject: str) -> dict[str, Any]:
        """Records the local<->OpenPower relationship as metadata only -- never a password
        or browser refresh token."""
        return {"local_actor": local_actor_id, "openpower_subject": openpower_subject, "linked_at": time.strftime("%Y-%m-%dT%H:%M:%S+00:00", time.gmtime())}

    def link_agent(self, local_actor_id: str, openpower_subject: str) -> dict[str, Any]:
        return self.link_human(local_actor_id, openpower_subject)
