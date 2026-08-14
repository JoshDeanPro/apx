"""Agent credential secret generation, hashing, and verification.

Secrets are generated with `secrets.token_urlsafe` (CSPRNG, stdlib) and only
a salted argon2 hash (via passlib) is ever persisted — the plaintext is
returned to the caller exactly once, at creation/rotation time, and is never
logged or stored. Argon2 is used (over a bare hashlib.sha256) because it is
a memory-hard password-hashing KDF designed to resist brute force even if
the hash table leaks, which is the right tradeoff for a bearer credential
whose entropy an attacker might try to guess offline.
"""
from __future__ import annotations

import secrets
import uuid
from datetime import datetime, timezone

from passlib.context import CryptContext
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from .db import AgentCredential

_pwd_context = CryptContext(schemes=["argon2"], deprecated="auto")


def generate_credential_id() -> str:
    return f"cred_{uuid.uuid4().hex[:24]}"


def generate_secret() -> str:
    return secrets.token_urlsafe(32)


def generate_device_code() -> str:
    """Long, opaque, held only by the CLI -- never shown to or typed by a human."""
    return secrets.token_urlsafe(32)


# Excludes visually ambiguous characters (0/O, 1/I/L) since a human reads and
# types this one -- unlike device_code, which never leaves the CLI process.
_USER_CODE_ALPHABET = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"


def generate_user_code() -> str:
    half = lambda: "".join(secrets.choice(_USER_CODE_ALPHABET) for _ in range(4))
    return f"{half()}-{half()}"


def hash_secret(secret: str) -> str:
    return _pwd_context.hash(secret)


def verify_secret(secret: str, secret_hash: str) -> bool:
    try:
        return _pwd_context.verify(secret, secret_hash)
    except ValueError:
        return False


async def verify_credential(
    session: AsyncSession, *, credential_id: str, plaintext_secret: str
) -> AgentCredential | None:
    """Look up a credential by its public credential_id and verify the secret.

    Returns None (never raises) if the credential doesn't exist, is revoked,
    expired, or the secret doesn't match. This is the verification path a
    future agent-authentication endpoint (outside this V1 API's scope) would
    call; it's exercised directly by tests today.
    """
    result = await session.execute(
        select(AgentCredential).where(AgentCredential.credential_id == credential_id)
    )
    credential = result.scalar_one_or_none()
    if credential is None:
        return None
    if credential.revoked_at is not None:
        return None
    if credential.expires_at is not None:
        expires_at = credential.expires_at
        if expires_at.tzinfo is None:
            expires_at = expires_at.replace(tzinfo=timezone.utc)
        if expires_at < datetime.now(timezone.utc):
            return None
    if not verify_secret(plaintext_secret, credential.secret_hash):
        return None
    return credential
