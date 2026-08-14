"""Supabase user-JWT verification.

Chosen approach: PyJWT + Supabase's JWKS endpoint (asymmetric signing keys),
which is Supabase's current (2026) recommended verification path — see
https://supabase.com/docs/guides/auth/signing-keys and
https://supabase.com/docs/guides/auth/jwts. Supabase Auth signs user-session
JWTs with an asymmetric key (ES256 by default for new projects, RS256 also
supported) and publishes the public keys at
`<SUPABASE_URL>/auth/v1/.well-known/jwks.json`. Verifying against the public
key means this service never holds a shared signing secret and keys can
rotate on Supabase's side without a redeploy here.

We do NOT hand-roll any JWT crypto: PyJWT (with its `cryptography` extra)
performs signature verification. A `PyJWKClient` fetches and caches the
JWKS document and picks the correct key by the token's `kid` header.

A legacy HS256 fallback (`SUPABASE_JWT_LEGACY_HS256_SECRET`) exists only for
Supabase projects that have not yet migrated off the old shared-secret JWT
model; new deployments should leave it unset and rely on JWKS.

Every unsigned/invalid/expired/malformed/wrong-audience token is rejected
with 401 — we never trust claims from a token whose signature didn't verify,
and we never trust identity fields from the request body.
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import Any, Protocol

import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from .config import get_settings


class AuthError(Exception):
    pass


class SigningKeyResolver(Protocol):
    def resolve(self, token: str) -> Any:
        ...


class JWKSSigningKeyResolver:
    """Production resolver: fetches/caches Supabase's public JWKS over HTTPS."""

    def __init__(self, jwks_url: str):
        if not jwks_url:
            raise ValueError("SUPABASE_URL or SUPABASE_JWKS_URL must be configured")
        self._client = jwt.PyJWKClient(jwks_url, cache_keys=True, lifespan=600)

    def resolve(self, token: str) -> Any:
        return self._client.get_signing_key_from_jwt(token).key


class StaticSigningKeyResolver:
    """Test resolver: verifies against a fixed in-memory public key, no network."""

    def __init__(self, key: Any):
        self._key = key

    def resolve(self, token: str) -> Any:
        return self._key


_resolver_override: SigningKeyResolver | None = None
_cached_resolver: SigningKeyResolver | None = None


def set_resolver_override(resolver: SigningKeyResolver | None) -> None:
    """Test hook: force a specific signing-key resolver, bypassing JWKS/network."""
    global _resolver_override
    _resolver_override = resolver


def get_resolver() -> SigningKeyResolver:
    global _cached_resolver
    if _resolver_override is not None:
        return _resolver_override
    if _cached_resolver is None:
        settings = get_settings()
        _cached_resolver = JWKSSigningKeyResolver(settings.jwks_url)
    return _cached_resolver


def verify_token(token: str) -> dict:
    """Verify a Supabase-issued user JWT and return its claims.

    Raises AuthError on any failure (bad signature, expired, malformed,
    wrong audience/issuer). Never returns claims for a token that failed
    signature verification.
    """
    settings = get_settings()
    errors: list[str] = []

    try:
        resolver = get_resolver()
        key = resolver.resolve(token)
        claims = jwt.decode(
            token,
            key,
            algorithms=settings.jwt_algorithms,
            audience=settings.supabase_jwt_audience,
            options={"require": ["exp", "sub"]},
        )
        return claims
    except Exception as exc:  # noqa: BLE001 - collect and try legacy fallback below
        errors.append(f"jwks: {exc}")

    if settings.supabase_jwt_legacy_hs256_secret:
        try:
            claims = jwt.decode(
                token,
                settings.supabase_jwt_legacy_hs256_secret,
                algorithms=["HS256"],
                audience=settings.supabase_jwt_audience,
                options={"require": ["exp", "sub"]},
            )
            return claims
        except Exception as exc:  # noqa: BLE001
            errors.append(f"legacy_hs256: {exc}")

    raise AuthError("; ".join(errors) or "token verification failed")


@dataclass
class AuthenticatedUser:
    id: uuid.UUID
    email: str | None = None
    claims: dict = field(default_factory=dict)


_bearer_scheme = HTTPBearer(auto_error=False)


async def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer_scheme),
) -> AuthenticatedUser:
    if credentials is None or not credentials.credentials:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Missing bearer token")

    try:
        claims = verify_token(credentials.credentials)
    except AuthError:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid authentication token")

    sub = claims.get("sub")
    if not sub:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Token missing subject claim")

    try:
        user_id = uuid.UUID(str(sub))
    except ValueError:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid subject claim")

    return AuthenticatedUser(id=user_id, email=claims.get("email"), claims=claims)
