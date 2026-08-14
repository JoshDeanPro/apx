"""Verifies the HS256 identity tokens AXP presents back to this API --
the inverse of openpower_axp.mint_jwt_hs256, which mints them. Same shared
secret, same claim shape (sub=identity_key, iss=openpower.one, aud=axp).

Uses PyJWT for verification (already a dependency, used for Supabase JWTs in
auth.py) rather than the stdlib-only hand-rolled verifier AXP's own
auth_openpower.py uses -- that hand-rolled version exists specifically to
avoid a new dependency on AXP's side; this service already depends on PyJWT,
so there's no reason to hand-roll a second HS256 verifier here.

This is a *device/agent* principal, structurally different from
AuthenticatedUser (auth.py) -- a human's Supabase session proves "which
person," this proves "which of that person's linked AXP instances." Every
route using this must still scope by the resolved owner_id, exactly like
every human-authenticated route already does.
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass

import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from .config import get_settings
from .db import AgentIdentity, get_session


@dataclass
class AuthenticatedAgent:
    identity_key: str
    agent_id: uuid.UUID
    owner_id: uuid.UUID


_bearer_scheme = HTTPBearer(auto_error=False)


async def get_current_agent(
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer_scheme),
    session: AsyncSession = Depends(get_session),
) -> AuthenticatedAgent:
    if credentials is None or not credentials.credentials:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Missing bearer token")

    settings = get_settings()
    if not settings.openpower_axp_shared_secret:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="AXP agent authentication is not configured on this server",
        )

    try:
        claims = jwt.decode(
            credentials.credentials,
            settings.openpower_axp_shared_secret,
            algorithms=["HS256"],
            audience="axp",
            issuer="openpower.one",
            options={"require": ["exp", "sub"]},
        )
    except jwt.PyJWTError:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid agent token")

    identity_key = str(claims["sub"])
    result = await session.execute(select(AgentIdentity).where(AgentIdentity.identity_key == identity_key))
    identity = result.scalar_one_or_none()
    if identity is None or identity.status != "active":
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Unknown or inactive agent identity")

    return AuthenticatedAgent(identity_key=identity_key, agent_id=identity.agent_id, owner_id=identity.owner_id)
