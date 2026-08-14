"""Append-only audit logging.

audit_events is service-role-insert-only by RLS design (see schema.sql:
no insert policy exists for the `authenticated` role), so this service's
privileged Postgres connection is the only writer. Never pass a credential
secret (plaintext or hash) in `metadata` — callers must not include it.
"""
from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from .db import AuditEvent

# Defense in depth: reject metadata that looks like it might carry a secret.
_FORBIDDEN_METADATA_KEYS = {"secret", "secret_hash", "plaintext", "password", "token"}


async def record_audit_event(
    session: AsyncSession,
    *,
    owner_id: uuid.UUID,
    actor: str,
    event_type: str,
    target: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> None:
    metadata = metadata or {}
    bad_keys = _FORBIDDEN_METADATA_KEYS & set(metadata.keys())
    if bad_keys:
        raise ValueError(f"audit metadata must not contain sensitive keys: {bad_keys}")

    event = AuditEvent(
        owner_id=owner_id,
        actor=actor,
        event_type=event_type,
        target=target,
        audit_metadata=metadata,
    )
    session.add(event)
