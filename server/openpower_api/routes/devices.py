"""Human-authenticated device control: queue a command for a device, see its
status/result. The device itself only ever reaches this data through
routes/agent.py's agent-token-authenticated poll/report endpoints -- a human
never talks to a device directly, and a device never receives a command
except by polling for it. Actions are restricted to a fixed, safe allowlist
(status/restart/logs) -- this is not arbitrary remote code execution.
"""
from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..audit import record_audit_event
from ..auth import AuthenticatedUser, get_current_user
from ..db import Device, DeviceCommand, get_session
from ..ratelimit import rate_limited
from ..schemas import ALLOWED_COMMAND_ACTIONS, CommandCreate, CommandOut

router = APIRouter(prefix="/devices", tags=["devices"])


async def _get_owned_device(session: AsyncSession, device_id: uuid.UUID, owner_id: uuid.UUID) -> Device:
    result = await session.execute(select(Device).where(Device.id == device_id))
    device = result.scalar_one_or_none()
    if device is None or device.owner_id != owner_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Device not found")
    return device


@router.post("/{device_id}/commands", response_model=CommandOut, status_code=status.HTTP_201_CREATED)
async def create_command(
    device_id: uuid.UUID,
    body: CommandCreate,
    user: AuthenticatedUser = Depends(rate_limited("device_command_create")),
    session: AsyncSession = Depends(get_session),
) -> DeviceCommand:
    if body.action not in ALLOWED_COMMAND_ACTIONS:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=f"action must be one of {sorted(ALLOWED_COMMAND_ACTIONS)}",
        )
    device = await _get_owned_device(session, device_id, user.id)

    command = DeviceCommand(owner_id=user.id, device_id=device.id, action=body.action, params=body.params)
    session.add(command)
    await session.flush()

    await record_audit_event(
        session,
        owner_id=user.id,
        actor=f"user:{user.id}",
        event_type="device_command.created",
        target=str(command.id),
        metadata={"device_id": str(device.id), "action": body.action},
    )
    await session.commit()
    await session.refresh(command)
    return command


@router.get("/{device_id}/commands", response_model=list[CommandOut])
async def list_commands(
    device_id: uuid.UUID,
    user: AuthenticatedUser = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> list[DeviceCommand]:
    device = await _get_owned_device(session, device_id, user.id)
    result = await session.execute(
        select(DeviceCommand)
        .where(DeviceCommand.device_id == device.id)
        .order_by(DeviceCommand.created_at.desc())
        .limit(20)
    )
    return list(result.scalars().all())
