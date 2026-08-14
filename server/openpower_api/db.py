"""Database layer.

Chosen approach: SQLAlchemy 2.0 async ORM (asyncpg driver) against the same
Postgres database Supabase manages, connected with a privileged Postgres
role (service-role-equivalent) rather than the `supabase-py` client.

Why SQLAlchemy + asyncpg over supabase-py:
  - supabase-py's server-side usage still goes through PostgREST/HTTP, which
    adds latency and an extra JSON-shape translation layer for what is,
    here, first-party server code running next to the database.
  - A direct async Postgres connection gives real transactions (needed for
    "create credential row + audit row" atomicity) and lets the same code
    run against SQLite in tests (see below), which PostgREST/supabase-py
    cannot do.
  - RLS is Postgres-native and applies to the `authenticated`/`anon` roles;
    a privileged direct connection bypasses it by design (that's what
    "service role" access means here), so this module + every route MUST
    keep doing explicit owner_id checks in Python. RLS policies in
    ~/openpower/db/schema.sql remain the correct enforcement for the
    browser/PostgREST path; they are not enforced on this connection.

Why SQLite fallback for tests: the test suite must run without a live
Supabase project. SQLAlchemy's dialect abstraction lets the exact same ORM
models and queries run against `sqlite+aiosqlite:///...` in tests and
`postgresql+asyncpg://...` in production. The tradeoff: SQLite does not
enforce the same JSONB/UUID semantics or RLS as Postgres, so this is a unit/
integration test of the application layer's own authorization logic (the
owner_id checks this service is responsible for), not a substitute for
testing Postgres RLS itself.
"""
from __future__ import annotations

import uuid
from datetime import datetime
from typing import AsyncIterator

from sqlalchemy import JSON, DateTime, ForeignKey, String, Text, TypeDecorator, Uuid, func
from sqlalchemy.dialects.postgresql import ARRAY as PG_ARRAY
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from sqlalchemy.pool import StaticPool


class TextArray(TypeDecorator):
    """Postgres `text[]` on the real database; JSON-encoded TEXT on SQLite
    (which has no native array type), so the same model runs against both --
    same tradeoff as the rest of this file's dialect abstraction."""

    impl = Text
    cache_ok = True

    def load_dialect_impl(self, dialect):
        if dialect.name == "postgresql":
            return dialect.type_descriptor(PG_ARRAY(Text()))
        return dialect.type_descriptor(Text())

    def process_bind_param(self, value, dialect):
        if dialect.name == "postgresql":
            return value
        import json

        return json.dumps(value or [])

    def process_result_value(self, value, dialect):
        if dialect.name == "postgresql" or value is None:
            return value or []
        import json

        return json.loads(value)

from .config import get_settings


class Base(DeclarativeBase):
    pass


def _uuid_col(*, primary_key: bool = False, default_random: bool = False, nullable: bool = False, unique: bool = False):
    kwargs = dict(primary_key=primary_key, nullable=nullable, unique=unique)
    if default_random:
        kwargs["default"] = uuid.uuid4
    return mapped_column(Uuid(as_uuid=True), **kwargs)


class Profile(Base):
    __tablename__ = "profiles"

    id: Mapped[uuid.UUID] = _uuid_col(primary_key=True)
    display_name: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Device(Base):
    """Mirrors public.devices (see ~/openpower/db/schema.sql). Owned by
    Supabase/RLS for the browser path; this model lets the same table be
    read/written from FastAPI (MCP tools) with its own owner_id checks."""

    __tablename__ = "devices"

    id: Mapped[uuid.UUID] = _uuid_col(primary_key=True, default_random=True)
    owner_id: Mapped[uuid.UUID] = _uuid_col()
    name: Mapped[str] = mapped_column(Text)
    type: Mapped[str] = mapped_column(Text, default="unknown")
    status: Mapped[str] = mapped_column(Text, default="disconnected")
    last_seen: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    axp_version: Mapped[str | None] = mapped_column(Text, nullable=True)
    buddy_os_version: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class ServiceConnection(Base):
    __tablename__ = "service_connections"

    id: Mapped[uuid.UUID] = _uuid_col(primary_key=True, default_random=True)
    owner_id: Mapped[uuid.UUID] = _uuid_col()
    provider: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(Text, default="needs_setup")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Prompt(Base):
    __tablename__ = "prompts"

    id: Mapped[uuid.UUID] = _uuid_col(primary_key=True, default_random=True)
    owner_id: Mapped[uuid.UUID] = _uuid_col()
    name: Mapped[str] = mapped_column(Text)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    content: Mapped[str] = mapped_column(Text, default="")
    tags: Mapped[list[str]] = mapped_column(TextArray, default=list)
    version: Mapped[int] = mapped_column(default=1)
    scope: Mapped[str] = mapped_column(Text, default="private")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Project(Base):
    __tablename__ = "projects"

    id: Mapped[uuid.UUID] = _uuid_col(primary_key=True, default_random=True)
    owner_id: Mapped[uuid.UUID] = _uuid_col()
    name: Mapped[str] = mapped_column(Text)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(Text, default="active")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Mission(Base):
    __tablename__ = "missions"

    id: Mapped[uuid.UUID] = _uuid_col(primary_key=True, default_random=True)
    owner_id: Mapped[uuid.UUID] = _uuid_col()
    project_id: Mapped[uuid.UUID] = _uuid_col()
    title: Mapped[str] = mapped_column(Text)
    objective: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(Text, default="draft")
    assigned_agent_id: Mapped[uuid.UUID | None] = _uuid_col(nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class DeviceCommand(Base):
    """Live device control: a human queues one, the device's own AXP polls
    for it and reports a result. See routes/agent.py and routes/devices.py."""

    __tablename__ = "device_commands"

    id: Mapped[uuid.UUID] = _uuid_col(primary_key=True, default_random=True)
    owner_id: Mapped[uuid.UUID] = _uuid_col()
    device_id: Mapped[uuid.UUID] = _uuid_col()
    action: Mapped[str] = mapped_column(Text)
    params: Mapped[dict] = mapped_column(JSON, default=dict)
    status: Mapped[str] = mapped_column(Text, default="pending")
    result: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class AgentProfile(Base):
    __tablename__ = "agent_profiles"

    id: Mapped[uuid.UUID] = _uuid_col(primary_key=True, default_random=True)
    owner_id: Mapped[uuid.UUID] = _uuid_col()
    name: Mapped[str] = mapped_column(Text)
    provider: Mapped[str | None] = mapped_column(Text, nullable=True)
    device_id: Mapped[uuid.UUID | None] = _uuid_col(nullable=True)
    status: Mapped[str] = mapped_column(Text, default="inactive")
    permissions: Mapped[dict] = mapped_column(JSON, default=dict)
    last_seen: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class AgentIdentity(Base):
    __tablename__ = "agent_identities"

    id: Mapped[uuid.UUID] = _uuid_col(primary_key=True, default_random=True)
    agent_id: Mapped[uuid.UUID] = _uuid_col(unique=True)
    owner_id: Mapped[uuid.UUID] = _uuid_col()
    identity_key: Mapped[str] = mapped_column(Text, unique=True)
    status: Mapped[str] = mapped_column(Text, default="active")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class AgentEnrollmentRequest(Base):
    __tablename__ = "agent_enrollment_requests"

    id: Mapped[uuid.UUID] = _uuid_col(primary_key=True, default_random=True)
    owner_id: Mapped[uuid.UUID] = _uuid_col()
    agent_name: Mapped[str] = mapped_column(Text)
    device_id: Mapped[uuid.UUID | None] = _uuid_col(nullable=True)
    requested_permissions: Mapped[dict] = mapped_column(JSON, default=dict)
    status: Mapped[str] = mapped_column(Text, default="pending")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # Set when a request is approved: the agent_profiles row created/assigned as a result.
    resulting_agent_id: Mapped[uuid.UUID | None] = _uuid_col(nullable=True)


class AgentCredential(Base):
    __tablename__ = "agent_credentials"

    id: Mapped[uuid.UUID] = _uuid_col(primary_key=True, default_random=True)
    agent_id: Mapped[uuid.UUID] = _uuid_col()
    owner_id: Mapped[uuid.UUID] = _uuid_col()
    credential_id: Mapped[str] = mapped_column(Text, unique=True)
    secret_hash: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    rotated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class DeviceLinkRequest(Base):
    """OAuth-device-authorization-style link: AXP requests a code, the human
    approves it inside the website's own authenticated session -- never a
    bare localhost/terminal flow the website has no way to observe."""

    __tablename__ = "device_link_requests"

    id: Mapped[uuid.UUID] = _uuid_col(primary_key=True, default_random=True)
    device_code: Mapped[str] = mapped_column(Text, unique=True)
    user_code: Mapped[str] = mapped_column(Text, unique=True)
    agent_name: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(Text, default="pending")
    owner_id: Mapped[uuid.UUID | None] = _uuid_col(nullable=True)
    agent_id: Mapped[uuid.UUID | None] = _uuid_col(nullable=True)
    identity_key: Mapped[str | None] = mapped_column(Text, nullable=True)
    last_polled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class AuditEvent(Base):
    __tablename__ = "audit_events"

    id: Mapped[uuid.UUID] = _uuid_col(primary_key=True, default_random=True)
    owner_id: Mapped[uuid.UUID] = _uuid_col()
    actor: Mapped[str] = mapped_column(Text)
    event_type: Mapped[str] = mapped_column(Text)
    target: Mapped[str | None] = mapped_column(Text, nullable=True)
    audit_metadata: Mapped[dict] = mapped_column("metadata", JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


_engine = None
_sessionmaker: async_sessionmaker[AsyncSession] | None = None


def get_engine():
    global _engine
    if _engine is None:
        settings = get_settings()
        kwargs: dict = {"echo": False}
        if settings.is_sqlite and ":memory:" in settings.database_url:
            # Keep a single shared connection alive for the whole process so
            # the in-memory database isn't dropped between requests/sessions.
            kwargs["connect_args"] = {"check_same_thread": False}
            kwargs["poolclass"] = StaticPool
        _engine = create_async_engine(settings.database_url, **kwargs)
    return _engine


def get_sessionmaker() -> async_sessionmaker[AsyncSession]:
    global _sessionmaker
    if _sessionmaker is None:
        _sessionmaker = async_sessionmaker(get_engine(), expire_on_commit=False, class_=AsyncSession)
    return _sessionmaker


async def init_models() -> None:
    """Create tables. Used for the SQLite test fallback and local bootstrapping.

    In production against Postgres, the schema is owned by
    ~/openpower/db/schema.sql (applied via Supabase migrations) — this is a
    no-op safety net (create_all is idempotent) and never drops or alters.
    """
    engine = get_engine()
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


async def get_session() -> AsyncIterator[AsyncSession]:
    sessionmaker = get_sessionmaker()
    async with sessionmaker() as session:
        yield session


async def reset_engine_cache() -> None:
    """Test helper: drop cached engine/sessionmaker so Settings changes take effect."""
    global _engine, _sessionmaker
    if _engine is not None:
        await _engine.dispose()
    _engine = None
    _sessionmaker = None
