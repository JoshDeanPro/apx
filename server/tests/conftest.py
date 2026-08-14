"""Test fixtures.

Tradeoff (documented, per task spec): tests run against an in-process SQLite
database instead of a live Supabase/Postgres instance, via the same
SQLAlchemy models used in production (see openpower_api/db.py's module
docstring). This exercises the application layer's own logic — including
the owner_id authorization checks this service is responsible for — end to
end through real HTTP requests, but does NOT exercise Postgres Row Level
Security policies (those live in ~/openpower/db/schema.sql and are a
separate concern enforced only on the non-privileged PostgREST path).

JWTs are generated with a real EC keypair created in-process (via the
`cryptography` package) and signed with PyJWT, then verified through the
*real* verification code path in openpower_api.auth — the only thing
replaced is where the public key comes from (a static in-memory key instead
of an HTTPS fetch to Supabase's JWKS endpoint), via
auth.set_resolver_override(). This means auth.py's signature/expiry/
audience checks are genuinely tested, not bypassed.
"""
from __future__ import annotations

import os
import uuid
from datetime import datetime, timedelta, timezone

import jwt
import pytest
import pytest_asyncio
from cryptography.hazmat.primitives.asymmetric import ec
from httpx import ASGITransport, AsyncClient

os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///:memory:")
os.environ.setdefault("SUPABASE_URL", "https://test-project.supabase.co")
os.environ.setdefault("SUPABASE_JWT_ALGORITHMS", "ES256")
os.environ.setdefault("SUPABASE_JWT_AUDIENCE", "authenticated")
os.environ.setdefault("OPENPOWER_ENV", "development")
os.environ.setdefault("OPENPOWER_RATE_LIMIT_MAX", "1000")
os.environ.setdefault("OPENPOWER_RATE_LIMIT_WINDOW_SECONDS", "60")

from openpower_api import auth, db  # noqa: E402
from openpower_api.config import get_settings  # noqa: E402
from openpower_api.main import app  # noqa: E402
from openpower_api.ratelimit import reset_rate_limits  # noqa: E402

_PRIVATE_KEY = ec.generate_private_key(ec.SECP256R1())
_PUBLIC_KEY = _PRIVATE_KEY.public_key()


def make_token(
    *,
    sub: str | None = None,
    email: str = "user@example.com",
    expires_in: timedelta = timedelta(hours=1),
    audience: str = "authenticated",
    algorithm: str = "ES256",
    key=None,
) -> str:
    sub = sub or str(uuid.uuid4())
    now = datetime.now(timezone.utc)
    payload = {
        "sub": sub,
        "email": email,
        "aud": audience,
        "role": "authenticated",
        "iat": now,
        "exp": now + expires_in,
    }
    return jwt.encode(payload, key or _PRIVATE_KEY, algorithm=algorithm)


@pytest.fixture(autouse=True)
def _reset_state():
    get_settings.cache_clear()
    auth.set_resolver_override(auth.StaticSigningKeyResolver(_PUBLIC_KEY))
    reset_rate_limits()
    yield
    auth.set_resolver_override(None)
    reset_rate_limits()


@pytest_asyncio.fixture(autouse=True)
async def _init_db():
    # Fresh in-memory SQLite database per test: dispose any cached engine so
    # a brand-new (empty) :memory: database is created for this test only.
    await db.reset_engine_cache()
    await db.init_models()
    yield
    await db.reset_engine_cache()


@pytest_asyncio.fixture
async def client():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


@pytest.fixture
def new_user_id() -> uuid.UUID:
    return uuid.uuid4()


@pytest.fixture
def auth_header():
    def _make(user_id: uuid.UUID | None = None, **kwargs) -> dict[str, str]:
        token = make_token(sub=str(user_id) if user_id else None, **kwargs)
        return {"Authorization": f"Bearer {token}"}

    return _make
