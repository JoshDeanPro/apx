from __future__ import annotations

import json
import sqlite3

import pytest

from apx.axp import ActionRequest, PreparedAction, StructuredError, validate_action_transition
from apx.providers import ActionProvider
from apx.runtime import OperationAccepted, ProviderSession


@pytest.mark.parametrize(
    ("current", "next_status"),
    [
        ("prepared", "authorized"),
        ("prepared", "accepted"),
        ("prepared", "cancelled"),
        ("authorized", "accepted"),
        ("authorized", "cancelled"),
        ("accepted", "in-progress"),
        ("accepted", "completed"),
        ("accepted", "failed"),
        ("accepted", "denied"),
        ("in-progress", "completed"),
        ("in-progress", "failed"),
        ("in-progress", "verification_failed"),
        ("pending", "prepared"),
        ("scheduled", "pending"),
        ("awaiting-input", "prepared"),
        ("awaiting-approval", "authorized"),
    ],
)
def test_valid_action_lifecycle_transitions(current, next_status):
    assert validate_action_transition(current, next_status) is None


@pytest.mark.parametrize(
    ("current", "next_status"),
    [
        ("completed", "in-progress"),
        ("failed", "accepted"),
        ("cancelled", "completed"),
        ("rejected", "prepared"),
        ("denied", "authorized"),
        ("prepared", "completed"),
        ("authorized", "in-progress"),
        ("accepted", "cancelled"),
        ("in-progress", "cancelled"),
        ("available", "completed"),
        ("unavailable", "prepared"),
    ],
)
def test_invalid_action_lifecycle_transitions_raise(current, next_status):
    with pytest.raises(ValueError, match="invalid action lifecycle transition"):
        validate_action_transition(current, next_status)


def test_same_state_writes_require_explicit_restore_mode():
    with pytest.raises(ValueError, match="invalid action lifecycle transition"):
        validate_action_transition("completed", "completed")
    assert validate_action_transition("completed", "completed", allow_same=True) is None


def test_prepared_action_rejects_definition_or_unknown_status():
    with pytest.raises(ValueError, match="invalid prepared action status"):
        PreparedAction(action="demo", status="available")

    with pytest.raises(ValueError, match="invalid prepared action status"):
        PreparedAction(action="demo", status="not-a-state")

    assert PreparedAction(action="demo", status="completed").status == "completed"


def _async_session(tmp_path, operation_id: str):
    provider = ActionProvider("test", "test")

    @provider.action(f"job.{operation_id}", risk="low_change", idempotent=True)
    def start():
        return OperationAccepted(operation_id)

    session = ProviderSession(provider, state_path=tmp_path / f"{operation_id}.sqlite")
    prepared = session.prepare(ActionRequest(f"job.{operation_id}", actor="human:operator"))
    assert isinstance(prepared, PreparedAction)
    accepted = session.execute(ActionRequest(
        f"job.{operation_id}",
        actor="human:operator",
        prepared_action_id=prepared.prepared_action_id,
        idempotency_key=operation_id,
    ))
    assert accepted.status == "accepted"
    return session, prepared


def test_completed_async_operation_and_prepared_state_restore_from_sqlite(tmp_path):
    session, prepared = _async_session(tmp_path, "op-1")
    completed = session.complete_operation("op-1", result={"done": True})
    assert completed.status == "completed"
    assert session.prepared[prepared.prepared_action_id].status == "completed"
    session.close()

    restored = ProviderSession(ActionProvider("test", "test"), state_path=tmp_path / "op-1.sqlite")
    restored_operation = restored.operation_status("op-1")
    assert restored_operation is not None
    assert restored_operation.status == "completed"
    assert restored.prepared[prepared.prepared_action_id].status == "completed"
    restored.close()


def test_failed_async_operation_survives_restart(tmp_path):
    session, prepared = _async_session(tmp_path, "op-failed")
    failed = session.complete_operation("op-failed", error=StructuredError("execution_failed", "worker failed"))
    assert failed.status == "failed"
    assert session.prepared[prepared.prepared_action_id].status == "failed"
    session.close()

    restored = ProviderSession(ActionProvider("test", "test"), state_path=tmp_path / "op-failed.sqlite")
    restored_failed = restored.operation_status("op-failed")
    assert restored_failed is not None
    assert restored_failed.status == "failed"
    assert restored.prepared[prepared.prepared_action_id].status == "failed"
    restored.close()


def test_verification_failed_async_operation_survives_restart(tmp_path):
    session, prepared = _async_session(tmp_path, "op-unverified")
    result = session.complete_operation("op-unverified", result={"done": False}, verified=False)
    assert result.status == "verification_failed"
    assert session.prepared[prepared.prepared_action_id].status == "verification_failed"
    session.close()

    restored = ProviderSession(ActionProvider("test", "test"), state_path=tmp_path / "op-unverified.sqlite")
    restored_unverified = restored.operation_status("op-unverified")
    assert restored_unverified is not None
    assert restored_unverified.status == "verification_failed"
    assert restored.prepared[prepared.prepared_action_id].status == "verification_failed"
    restored.close()


def test_duplicate_async_completion_returns_state_conflict(tmp_path):
    session, _ = _async_session(tmp_path, "op-duplicate")
    assert session.complete_operation("op-duplicate", result={"done": True}).status == "completed"
    duplicate = session.complete_operation("op-duplicate", result={"done": "again"})
    assert duplicate.status == "rejected"
    assert duplicate.error is not None
    assert duplicate.error.code == "state_conflict"
    restored_operation = session.operation_status("op-duplicate")
    assert restored_operation is not None
    assert restored_operation.result["done"] is True
    session.close()


def test_cancellation_after_async_commit_is_rejected(tmp_path):
    session, prepared = _async_session(tmp_path, "op-cancel")
    cancelled = session.cancel(prepared.prepared_action_id)
    assert cancelled.status == "rejected"
    assert cancelled.error is not None
    assert cancelled.error.code == "state_conflict"
    session.close()


def test_malformed_persisted_prepared_state_is_rejected(tmp_path):
    state_path = tmp_path / "state.sqlite"
    database = sqlite3.connect(state_path)
    database.execute("CREATE TABLE protocol_state (kind TEXT NOT NULL, key TEXT NOT NULL, value TEXT NOT NULL, PRIMARY KEY(kind,key))")
    database.execute("CREATE TABLE budget_events (actor TEXT NOT NULL, action TEXT NOT NULL, occurred REAL NOT NULL)")
    database.execute("INSERT INTO protocol_state(kind,key,value) VALUES(?,?,?)", ("prepared", "bad", json.dumps({"action": "demo", "status": "not-a-state"})))
    database.commit()
    database.close()

    with pytest.raises(ValueError, match="invalid prepared action status"):
        ProviderSession(ActionProvider("test", "test"), state_path=state_path)


def test_missing_authorization_returns_structured_expired_rejection():
    session = ProviderSession(ActionProvider("test", "test"))
    result = session.authorize("missing-prepared-action", {})

    assert result.status == "rejected"
    assert result.error is not None
    assert result.error.code == "expired"
