"""Pydantic request/response models. Identity fields (owner_id, user_id) are
never accepted from client input — they are always derived server-side from
the verified auth token."""
from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class HealthOut(BaseModel):
    status: str = "ok"


class ProfileOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    display_name: str | None = None
    email: str | None = None
    created_at: datetime
    updated_at: datetime


# --- Agents ------------------------------------------------------------------


class AgentCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    provider: str | None = None
    device_id: uuid.UUID | None = None
    permissions: dict[str, Any] = Field(default_factory=dict)


class AgentUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    provider: str | None = None
    device_id: uuid.UUID | None = None
    status: str | None = Field(default=None, pattern="^(active|inactive|disabled)$")
    permissions: dict[str, Any] | None = None


class AgentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    owner_id: uuid.UUID
    name: str
    provider: str | None
    device_id: uuid.UUID | None
    status: str
    permissions: dict[str, Any]
    last_seen: datetime | None
    created_at: datetime
    updated_at: datetime


# --- Agent identity ------------------------------------------------------------


class AgentIdentityCreate(BaseModel):
    identity_key: str | None = Field(
        default=None,
        max_length=200,
        description="If provided, assign this existing identity key to the agent. "
        "If omitted, a new identity key is generated.",
    )


class AgentIdentityOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    agent_id: uuid.UUID
    owner_id: uuid.UUID
    identity_key: str
    status: str
    created_at: datetime
    updated_at: datetime


# --- Credentials ---------------------------------------------------------------


class AgentCredentialCreate(BaseModel):
    expires_at: datetime | None = None


class AgentCredentialOut(BaseModel):
    """Never includes the secret. Used for every response after creation."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    agent_id: uuid.UUID
    credential_id: str
    created_at: datetime
    last_used_at: datetime | None
    expires_at: datetime | None
    rotated_at: datetime | None
    revoked_at: datetime | None


class AgentCredentialCreatedOut(AgentCredentialOut):
    """Returned exactly once, at creation/rotation time, with the plaintext secret."""

    secret: str


class AgentCredentialWithAgentOut(AgentCredentialOut):
    """Credential metadata joined with which agent it belongs to -- for the
    account-wide /credentials view, as opposed to one agent's own list."""

    agent_name: str


class AgentCredentialRotateIn(BaseModel):
    credential_id: str | None = Field(
        default=None,
        description="Which credential to rotate. If omitted, the agent's single "
        "most-recently-created active credential is rotated.",
    )


class AgentCredentialRevokeIn(BaseModel):
    credential_id: str


# --- AXP identity linking -------------------------------------------------------


class AXPTokenOut(BaseModel):
    """Returned once per mint. Not persisted server-side -- re-minting is always
    possible for the owner, so there is nothing to lose by not storing it."""

    identity_key: str
    token: str
    expires_at: datetime


class AXPStatusOut(BaseModel):
    revoked: bool


# --- Device linking (AXP <-> website, OAuth-device-authorization-style) --------


class DeviceLinkCreate(BaseModel):
    agent_name: str = Field(min_length=1, max_length=200, description="Shown to the human approving this link, e.g. \"AXP on workstation\".")


class DeviceLinkCreatedOut(BaseModel):
    device_code: str
    user_code: str
    verification_uri: str
    expires_in: int
    interval: int


class DeviceTokenIn(BaseModel):
    device_code: str


class DeviceTokenOut(BaseModel):
    """Returned exactly once, on the poll that observes 'approved'. Never
    retrievable again -- device_link_requests.status flips to 'consumed'."""

    identity_key: str
    token: str
    expires_at: datetime


class DeviceTokenPending(BaseModel):
    error: str = Field(description="authorization_pending | slow_down | expired_token | access_denied")


class DeviceLinkLookupOut(BaseModel):
    """What the website shows the human before they approve/deny."""

    agent_name: str
    status: str
    expires_at: datetime


class DeviceLinkDecision(BaseModel):
    user_code: str


class DeviceLinkApprovedOut(BaseModel):
    agent_id: uuid.UUID
    identity_key: str


# --- Live device control (heartbeat, AI-CLI detection, command dispatch) -------


class DetectedAgent(BaseModel):
    name: str
    provider: str


class HeartbeatIn(BaseModel):
    device_name: str = Field(min_length=1, max_length=200)
    device_type: str = "unknown"
    buddy_os_version: str | None = None
    axp_version: str | None = None
    detected_agents: list[DetectedAgent] = Field(default_factory=list)


class HeartbeatOut(BaseModel):
    device_id: uuid.UUID
    pending_commands: int


class ConnectionOut(BaseModel):
    """One other device on the same account, as seen by an already-linked
    device's own CLI -- 'apx connections list'. Lets an AI on one machine
    discover what else it can target with --target."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    type: str
    status: str
    last_seen: datetime | None


ALLOWED_COMMAND_ACTIONS = {
    "service.status",
    "service.restart",
    "logs.read",
    "host.status",
    "host.restart",
    "host.shutdown",
}


class CommandCreate(BaseModel):
    action: str
    params: dict[str, Any] = Field(default_factory=dict)


class CommandOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    device_id: uuid.UUID
    action: str
    params: dict[str, Any]
    status: str
    result: dict[str, Any] | None
    error: str | None
    created_at: datetime
    started_at: datetime | None
    completed_at: datetime | None


class CommandResultIn(BaseModel):
    status: str = Field(pattern="^(completed|failed)$")
    result: dict[str, Any] | None = None
    error: str | None = None


# --- Enrollments ---------------------------------------------------------------


class EnrollmentCreate(BaseModel):
    agent_name: str = Field(min_length=1, max_length=200)
    device_id: uuid.UUID | None = None
    requested_permissions: dict[str, Any] = Field(default_factory=dict)


class EnrollmentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    owner_id: uuid.UUID
    agent_name: str
    device_id: uuid.UUID | None
    requested_permissions: dict[str, Any]
    status: str
    created_at: datetime
    decided_at: datetime | None
    resulting_agent_id: uuid.UUID | None
