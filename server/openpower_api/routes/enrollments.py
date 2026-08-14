from __future__ import annotations

import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..audit import record_audit_event
from ..auth import AuthenticatedUser, get_current_user
from ..db import AgentEnrollmentRequest, AgentIdentity, AgentProfile, get_session
from ..ratelimit import rate_limited
from ..schemas import EnrollmentCreate, EnrollmentOut
from .agents import actor_for

router = APIRouter(prefix="/agent-enrollments", tags=["agent-enrollments"])


async def _get_owned_enrollment(
    session: AsyncSession, enrollment_id: uuid.UUID, owner_id: uuid.UUID
) -> AgentEnrollmentRequest:
    result = await session.execute(
        select(AgentEnrollmentRequest).where(AgentEnrollmentRequest.id == enrollment_id)
    )
    enrollment = result.scalar_one_or_none()
    if enrollment is None or enrollment.owner_id != owner_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Enrollment request not found")
    return enrollment


@router.get("", response_model=list[EnrollmentOut])
async def list_enrollments(
    user: AuthenticatedUser = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> list[AgentEnrollmentRequest]:
    result = await session.execute(
        select(AgentEnrollmentRequest).where(AgentEnrollmentRequest.owner_id == user.id)
    )
    return list(result.scalars().all())


@router.post("", response_model=EnrollmentOut, status_code=status.HTTP_201_CREATED)
async def create_enrollment(
    body: EnrollmentCreate,
    user: AuthenticatedUser = Depends(rate_limited("enrollment_create")),
    session: AsyncSession = Depends(get_session),
) -> AgentEnrollmentRequest:
    enrollment = AgentEnrollmentRequest(
        owner_id=user.id,
        agent_name=body.agent_name,
        device_id=body.device_id,
        requested_permissions=body.requested_permissions,
        status="pending",
    )
    session.add(enrollment)
    await session.flush()

    await record_audit_event(
        session,
        owner_id=user.id,
        actor=actor_for(user),
        event_type="agent.enrollment.requested",
        target=str(enrollment.id),
        metadata={"agent_name": enrollment.agent_name},
    )
    await session.commit()
    await session.refresh(enrollment)
    return enrollment


@router.post("/{enrollment_id}/approve", response_model=EnrollmentOut)
async def approve_enrollment(
    enrollment_id: uuid.UUID,
    user: AuthenticatedUser = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> AgentEnrollmentRequest:
    enrollment = await _get_owned_enrollment(session, enrollment_id, user.id)
    if enrollment.status != "pending":
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Enrollment already decided")

    # Approving creates (or reuses) the AgentProfile and gives it an active
    # OpenPower Agent Identity in one step.
    agent = AgentProfile(
        owner_id=user.id,
        name=enrollment.agent_name,
        device_id=enrollment.device_id,
        permissions=enrollment.requested_permissions,
        status="active",
    )
    session.add(agent)
    await session.flush()

    identity = AgentIdentity(
        agent_id=agent.id,
        owner_id=user.id,
        identity_key=f"agent:enrolled:{uuid.uuid4().hex[:12]}",
        status="active",
    )
    session.add(identity)

    enrollment.status = "approved"
    enrollment.decided_at = datetime.now(timezone.utc)
    enrollment.resulting_agent_id = agent.id
    await session.flush()

    await record_audit_event(
        session,
        owner_id=user.id,
        actor=actor_for(user),
        event_type="agent.enrollment.approved",
        target=str(enrollment.id),
        metadata={"agent_id": str(agent.id), "identity_key": identity.identity_key},
    )
    await session.commit()
    await session.refresh(enrollment)
    return enrollment


@router.post("/{enrollment_id}/deny", response_model=EnrollmentOut)
async def deny_enrollment(
    enrollment_id: uuid.UUID,
    user: AuthenticatedUser = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> AgentEnrollmentRequest:
    enrollment = await _get_owned_enrollment(session, enrollment_id, user.id)
    if enrollment.status != "pending":
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Enrollment already decided")

    enrollment.status = "denied"
    enrollment.decided_at = datetime.now(timezone.utc)
    await session.flush()

    await record_audit_event(
        session,
        owner_id=user.id,
        actor=actor_for(user),
        event_type="agent.enrollment.denied",
        target=str(enrollment.id),
    )
    await session.commit()
    await session.refresh(enrollment)
    return enrollment
