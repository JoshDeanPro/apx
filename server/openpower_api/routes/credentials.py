"""Account-wide credential overview -- every agent credential the signed-in
human owns, across all their agents. The per-agent list lives on
agents.py's /agents/{agent_id}/credentials; this is the /app/credentials
page's aggregate view."""
from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..auth import AuthenticatedUser, get_current_user
from ..db import AgentCredential, AgentProfile, get_session
from ..schemas import AgentCredentialWithAgentOut

router = APIRouter(tags=["credentials"])


@router.get("/credentials", response_model=list[AgentCredentialWithAgentOut])
async def list_all_credentials(
    user: AuthenticatedUser = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> list[AgentCredentialWithAgentOut]:
    result = await session.execute(
        select(AgentCredential, AgentProfile.name)
        .join(AgentProfile, AgentProfile.id == AgentCredential.agent_id)
        .where(AgentCredential.owner_id == user.id)
        .order_by(AgentCredential.created_at.desc())
    )
    return [
        AgentCredentialWithAgentOut(
            id=credential.id,
            agent_id=credential.agent_id,
            agent_name=agent_name,
            credential_id=credential.credential_id,
            created_at=credential.created_at,
            last_used_at=credential.last_used_at,
            expires_at=credential.expires_at,
            rotated_at=credential.rotated_at,
            revoked_at=credential.revoked_at,
        )
        for credential, agent_name in result.all()
    ]
