"""Endpoints AXP itself calls, authenticated with its own identity token
(agent_auth.get_current_agent) -- never a human's Supabase session. This is
the live bridge: self-registration/heartbeat (so Devices/Agents actually
populate from a real running AXP instance) and command polling/reporting
(so a human's dispatched command actually reaches and runs on the machine).
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..agent_auth import AuthenticatedAgent, get_current_agent
from ..audit import record_audit_event
from ..db import AgentProfile, Device, DeviceCommand, get_session
from ..schemas import (
    CommandCreate,
    CommandOut,
    CommandResultIn,
    ConnectionOut,
    HeartbeatIn,
    HeartbeatOut,
)
from ..schemas import ALLOWED_COMMAND_ACTIONS

router = APIRouter(prefix="/agent", tags=["agent"])


@router.post("/heartbeat", response_model=HeartbeatOut)
async def heartbeat(
    body: HeartbeatIn,
    agent: AuthenticatedAgent = Depends(get_current_agent),
    session: AsyncSession = Depends(get_session),
) -> HeartbeatOut:
    now = datetime.now(timezone.utc)

    # Find-or-create the device this heartbeat is reporting for, keyed by
    # (owner, name) -- the same device on every heartbeat, not a new row
    # each time.
    result = await session.execute(
        select(Device).where(Device.owner_id == agent.owner_id, Device.name == body.device_name)
    )
    device = result.scalar_one_or_none()
    if device is None:
        device = Device(owner_id=agent.owner_id, name=body.device_name, type=body.device_type, status="connected")
        session.add(device)
        await session.flush()
    else:
        device.type = body.device_type
        device.status = "connected"
    device.last_seen = now
    device.axp_version = body.axp_version
    device.buddy_os_version = body.buddy_os_version
    await session.flush()

    # Link the calling AgentProfile (the AXP instance itself) to this device.
    axp_agent = await session.execute(select(AgentProfile).where(AgentProfile.id == agent.agent_id))
    axp_agent_row = axp_agent.scalar_one_or_none()
    if axp_agent_row is not None:
        axp_agent_row.device_id = device.id
        axp_agent_row.status = "active"
        axp_agent_row.last_seen = now

    # Auto-detected AI CLIs: find-or-create by (owner, name), linked to this device.
    for detected in body.detected_agents:
        existing = await session.execute(
            select(AgentProfile).where(AgentProfile.owner_id == agent.owner_id, AgentProfile.name == detected.name)
        )
        row = existing.scalar_one_or_none()
        if row is None:
            row = AgentProfile(
                owner_id=agent.owner_id,
                name=detected.name,
                provider=detected.provider,
                device_id=device.id,
                status="detected",
            )
            session.add(row)
        else:
            row.device_id = device.id
            row.provider = detected.provider
            if row.status == "inactive":
                row.status = "detected"
        row.last_seen = now

    pending = await session.execute(
        select(DeviceCommand).where(DeviceCommand.device_id == device.id, DeviceCommand.status == "pending")
    )
    pending_count = len(pending.scalars().all())

    await record_audit_event(
        session,
        owner_id=agent.owner_id,
        actor=f"agent:{agent.identity_key}",
        event_type="device.heartbeat",
        target=str(device.id),
        metadata={"device_name": device.name, "detected_agents": [d.name for d in body.detected_agents]},
    )
    await session.commit()

    return HeartbeatOut(device_id=device.id, pending_commands=pending_count)


@router.get("/commands", response_model=list[CommandOut])
async def list_pending_commands(
    agent: AuthenticatedAgent = Depends(get_current_agent),
    session: AsyncSession = Depends(get_session),
) -> list[DeviceCommand]:
    axp_agent = await session.execute(select(AgentProfile).where(AgentProfile.id == agent.agent_id))
    axp_agent_row = axp_agent.scalar_one_or_none()
    if axp_agent_row is None or axp_agent_row.device_id is None:
        return []

    result = await session.execute(
        select(DeviceCommand).where(
            DeviceCommand.device_id == axp_agent_row.device_id, DeviceCommand.status == "pending"
        )
    )
    commands = result.scalars().all()
    for command in commands:
        command.status = "running"
        command.started_at = datetime.now(timezone.utc)
    await session.commit()
    return commands


@router.post("/commands/{command_id}/result", response_model=CommandOut)
async def report_command_result(
    command_id: uuid.UUID,
    body: CommandResultIn,
    agent: AuthenticatedAgent = Depends(get_current_agent),
    session: AsyncSession = Depends(get_session),
) -> DeviceCommand:
    result = await session.execute(
        select(DeviceCommand).where(DeviceCommand.id == command_id, DeviceCommand.owner_id == agent.owner_id)
    )
    command = result.scalar_one_or_none()
    if command is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Command not found")

    command.status = body.status
    command.result = body.result
    command.error = body.error
    command.completed_at = datetime.now(timezone.utc)

    await record_audit_event(
        session,
        owner_id=agent.owner_id,
        actor=f"agent:{agent.identity_key}",
        event_type="device_command.reported",
        target=str(command.id),
        metadata={"action": command.action, "status": command.status},
    )
    await session.commit()
    await session.refresh(command)
    return command


@router.get("/connections", response_model=list[ConnectionOut])
async def list_connections(
    agent: AuthenticatedAgent = Depends(get_current_agent),
    session: AsyncSession = Depends(get_session),
) -> list[Device]:
    """Every device on this account, as seen from one already-linked device's
    own CLI -- 'apx connections list'. This is what makes --target work: an
    AI has to discover what else it can dispatch a command to."""
    result = await session.execute(select(Device).where(Device.owner_id == agent.owner_id).order_by(Device.name))
    return list(result.scalars().all())


@router.post("/connections/{device_name}/commands", response_model=CommandOut, status_code=status.HTTP_201_CREATED)
async def create_connection_command(
    device_name: str,
    body: CommandCreate,
    agent: AuthenticatedAgent = Depends(get_current_agent),
    session: AsyncSession = Depends(get_session),
) -> DeviceCommand:
    """One linked device queuing a command for another linked device by name
    -- 'apx host shutdown home_server --target home_server'. Same allowlist
    as the human-facing route in routes/devices.py; the caller being an agent
    rather than a browser session doesn't relax it."""
    if body.action not in ALLOWED_COMMAND_ACTIONS:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=f"action must be one of {sorted(ALLOWED_COMMAND_ACTIONS)}",
        )
    result = await session.execute(
        select(Device).where(Device.owner_id == agent.owner_id, Device.name == device_name)
    )
    device = result.scalar_one_or_none()
    if device is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Device not found")

    command = DeviceCommand(owner_id=agent.owner_id, device_id=device.id, action=body.action, params=body.params)
    session.add(command)
    await session.flush()

    await record_audit_event(
        session,
        owner_id=agent.owner_id,
        actor=f"agent:{agent.identity_key}",
        event_type="device_command.created",
        target=str(command.id),
        metadata={"device_id": str(device.id), "device_name": device.name, "action": body.action},
    )
    await session.commit()
    await session.refresh(command)
    return command


@router.get("/commands/{command_id}", response_model=CommandOut)
async def get_command(
    command_id: uuid.UUID,
    agent: AuthenticatedAgent = Depends(get_current_agent),
    session: AsyncSession = Depends(get_session),
) -> DeviceCommand:
    """Poll the status of any command this account owns -- not just ones
    queued for the calling device -- so a CLI that just dispatched to a
    --target can watch for the result without a second channel."""
    result = await session.execute(
        select(DeviceCommand).where(DeviceCommand.id == command_id, DeviceCommand.owner_id == agent.owner_id)
    )
    command = result.scalar_one_or_none()
    if command is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Command not found")
    return command
