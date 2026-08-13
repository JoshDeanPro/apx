# SPDX-License-Identifier: MPL-2.0
"""Transport-neutral APX 0.1 provider lifecycle engine.

The registry describes actions.  This engine owns protocol state: preparation,
the commit boundary, provider policy, idempotency, locking, verification and
receipt recovery.  Transports are deliberately thin wrappers around it.
"""
from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta, timezone
import threading
from typing import Any, Callable

from jsonschema import ValidationError
from jsonschema.validators import Draft202012Validator

from .actions import ActionError
from .axp import ActionReceipt, ActionRequest, ActionResult, PreparedAction, StructuredError
from .credentials import CredentialRegistry
from .providers import ActionProvider


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _time(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


class ProviderPolicyDenied(ActionError):
    def __init__(self, message: str, *, provider_code: str | None = None, next_actions: tuple[str, ...] = ()):
        super().__init__(message)
        self.provider_code = provider_code
        self.next_actions = next_actions


class ProviderSession:
    """Reference state engine used identically by local and HTTP providers."""

    def __init__(self, provider: ActionProvider, *, policy: Callable[[ActionRequest], bool | tuple[bool, str]] | None = None,
                 prepare_ttl: int = 120):
        self.provider = provider
        self.policy = policy or (lambda _request: True)
        self.prepare_ttl = prepare_ttl
        self.prepared: dict[str, PreparedAction] = {}
        self.results: dict[str, ActionResult] = {}
        self.idempotency: dict[str, str] = {}
        self.operations: dict[str, ActionResult] = {}
        self._authorizations: set[str] = set()
        self._resource_locks: dict[str, threading.Lock] = {}
        self._last_execution: dict[tuple[str, str], datetime] = {}
        self._lock = threading.RLock()
        self.credentials = CredentialRegistry()

    def _action(self, action_id: str):
        item = self.provider._actions.get(action_id)  # registry remains authoritative
        if not item:
            raise KeyError(action_id)
        return item.registered

    def _error(self, request: ActionRequest, status: str, code: str, message: str, **kwargs: Any) -> ActionResult:
        result = ActionResult(request.action, False, request_id=request.request_id, target=request.target,
                              status=status, error=StructuredError(code, message, **kwargs))
        self.results[request.request_id] = result
        return result

    def _allowed(self, request: ActionRequest) -> tuple[bool, str]:
        decision = self.policy(request)
        if isinstance(decision, tuple):
            return bool(decision[0]), str(decision[1])
        return bool(decision), "provider policy denied the action"

    def prepare(self, request: ActionRequest) -> PreparedAction | ActionResult:
        try:
            action = self._action(request.action)
        except KeyError:
            return self._error(request, "rejected", "unsupported_action", "provider does not expose this action")
        try:
            Draft202012Validator(action.schema).validate(request.input)
        except ValidationError:
            return self._error(request, "rejected", "invalid_request", "input does not satisfy the action schema")
        allowed, reason = self._allowed(request)
        if not allowed:
            return self._error(request, "denied", "policy_denied", reason)
        values: dict[str, Any] = {}
        if action.prepare_handler:
            raw = action.prepare_handler(**request.input)
            values = dict(raw) if isinstance(raw, dict) else {}
        expires = _now() + timedelta(seconds=max(1, self.prepare_ttl))
        prepared = PreparedAction(
            action=action.name, target=request.target, input=request.input,
            effect=values.pop("effect", action.description), confirmation_required=action.confirmation,
            reversible=action.reversible, reverse_action=action.reverse_action,
            expires_at=values.pop("expires_at", expires.isoformat()), request_id=request.request_id,
            provider=self.provider.identity.id, side_effects=action.side_effects,
            authoritative_state_version=values.pop("authoritative_state_version", None),
            authoritative_state=values.pop("authoritative_state", None),
            preconditions=action.preconditions, resolved_terms=values.pop("resolved_terms", {}), **values,
        )
        self.prepared[prepared.prepared_action_id] = prepared
        return prepared

    def authorize(self, prepared_action_id: str, confirmation: dict[str, Any]) -> ActionResult:
        prepared = self.prepared.get(prepared_action_id)
        request = ActionRequest(prepared.action if prepared else "unknown", prepared_action_id=prepared_action_id)
        if not prepared:
            return self._error(request, "expired", "expired", "prepared action does not exist or has expired")
        if _time(prepared.expires_at) is None or _time(prepared.expires_at) <= _now():
            return self._error(request, "expired", "expired", "prepared action has expired")
        authorization_id = confirmation.get("authorization_id") or confirmation.get("nonce")
        valid = confirmation.get("confirmed") is True and confirmation.get("level") == prepared.confirmation_required
        valid = valid and confirmation.get("prepared_action_id") == prepared.prepared_action_id
        if prepared.confirmation_required == "transaction":
            valid = valid and confirmation.get("terms") == prepared.confirmation_terms
        if _time(confirmation.get("expires_at")) is not None:
            valid = valid and _time(confirmation.get("expires_at")) > _now()
        if not authorization_id or authorization_id in self._authorizations:
            valid = False
        if not valid:
            return self._error(request, "authorization_required", "confirmation_required",
                               "confirmation must bind to the unexpired prepared action")
        self._authorizations.add(authorization_id)
        authorized = replace(prepared, status="authorized")
        self.prepared[prepared_action_id] = authorized
        return ActionResult(prepared.action, True, result={"prepared_action_id": prepared_action_id},
                            request_id=prepared.request_id, target=prepared.target, status="authorized")

    def cancel(self, prepared_action_id: str) -> ActionResult:
        prepared = self.prepared.get(prepared_action_id)
        request = ActionRequest(prepared.action if prepared else "unknown", prepared_action_id=prepared_action_id)
        if not prepared:
            return self._error(request, "expired", "expired", "prepared action does not exist")
        if prepared.status in {"accepted", "executing", "completed"}:
            return self._error(request, "rejected", "state_conflict", "action crossed the commit boundary")
        self.prepared[prepared_action_id] = replace(prepared, status="cancelled")
        return ActionResult(prepared.action, True, request_id=prepared.request_id, target=prepared.target,
                            status="cancelled", result={"committed": False})

    def execute(self, request: ActionRequest) -> ActionResult:
        if request.idempotency_key and request.idempotency_key in self.idempotency:
            return self.results[self.idempotency[request.idempotency_key]]
        try:
            action = self._action(request.action)
        except KeyError:
            return self._error(request, "rejected", "unsupported_action", "provider does not expose this action")
        retry = action.definition().retry or ("safe" if action.read_only else "idempotency_required" if action._idempotent() else "never")
        if retry == "idempotency_required" and not request.idempotency_key:
            return self._error(request, "rejected", "invalid_request", "idempotency_key is required")
        prepared = self.prepared.get(request.prepared_action_id or "")
        if not action.read_only or action.confirmation != "none":
            if not prepared or prepared.action != request.action or prepared.input != request.input or prepared.target != request.target:
                return self._error(request, "rejected", "precondition_failed", "execute must match a prepared action")
            if prepared.status not in ({"authorized"} if action.confirmation != "none" else {"prepared"}):
                return self._error(request, "rejected", "confirmation_required", "prepared action is not authorized")
            if _time(prepared.expires_at) is None or _time(prepared.expires_at) <= _now():
                return self._error(request, "expired", "expired", "prepared action has expired")
            if request.authoritative_state_version != prepared.authoritative_state_version:
                return self._error(request, "rejected", "precondition_failed", "authoritative state version changed")
            if action.prepare_handler and prepared.authoritative_state_version is not None:
                current=action.prepare_handler(**request.input)
                current_version=current.get("authoritative_state_version") if isinstance(current,dict) else None
                if current_version != prepared.authoritative_state_version:
                    return self._error(request,"rejected","precondition_failed","provider authoritative state changed; prepare again")
        allowed, reason = self._allowed(request)
        if not allowed:
            return self._error(request, "denied", "policy_denied", reason)
        resource_key = str(sorted(request.target.items())) or request.action
        cooldown=int(action.definition().constraints.get("cooldown_seconds",0))
        last=self._last_execution.get((request.action,resource_key))
        if cooldown and last and (_now()-last).total_seconds()<cooldown:
            retry_after=max(1,cooldown-int((_now()-last).total_seconds()))
            return self._error(request,"rejected","cooldown_active","action cooldown is active",retryable=True,retry_after=retry_after)
        resource_lock = self._resource_locks.setdefault(resource_key, threading.Lock())
        if not resource_lock.acquire(blocking=False):
            return self._error(request, "rejected", "resource_locked", "a conflicting action is executing", retryable=True, retry_after=1)
        committed_at = _now().isoformat()
        if prepared:
            self.prepared[prepared.prepared_action_id] = replace(prepared, status="accepted")
        try:
            raw = action.handler(**request.input)
            data = self.credentials.redact(raw)
            verified = True
            if action.verify_handler:
                verified = bool(action.verify_handler(data, **request.input))
            status = "completed" if verified else "verification_failed"
            receipt = ActionReceipt(
                action=action.name, provider=self.provider.identity.id, target=request.target,
                actor=request.actor, delegated_by=request.delegated_by, status=status, result=data,
                request_id=request.request_id, prepared_action_id=request.prepared_action_id,
                committed_at=committed_at, completed_at=_now().isoformat(),
                verification_status="verified" if verified else "failed",
                verified_state=data if isinstance(data, dict) else None,
                postconditions=action.postconditions, reversible=action.reversible,
                reverse_action=action.reverse_action, side_effects=action.side_effects,
                reversal={"available": action.reversible, "action": action.reverse_action} if action.reversible else {"available": False},
            )
            result = ActionResult(action.name, verified, result=data,
                                  error=None if verified else StructuredError("verification_failed", "postconditions were not verified"),
                                  request_id=request.request_id, target=request.target, status=status, receipt=receipt)
            self.provider.receipts[receipt.receipt_id] = receipt
        except ProviderPolicyDenied as error:
            result = self._error(request, "denied", "policy_denied", str(error),
                                 provider_code=error.provider_code, next_actions=error.next_actions)
        except Exception as error:
            result = self._error(request, "failed", "execution_failed", self.credentials.redact_text(str(error)))
        finally:
            resource_lock.release()
        self.results[request.request_id] = result
        if result.status in {"completed","partial","verification_failed"}:
            self._last_execution[(request.action,resource_key)]=_now()
        if request.idempotency_key:
            self.idempotency[request.idempotency_key] = request.request_id
        return result

    def status(self, request_id: str) -> ActionResult | None:
        return self.results.get(request_id)

    def receipt(self, receipt_id: str) -> ActionReceipt | None:
        return self.provider.get_receipt(receipt_id)

    def reverse(self, receipt_id: str, request: ActionRequest) -> ActionResult:
        receipt = self.receipt(receipt_id)
        if not receipt or not receipt.reversible or not receipt.reverse_action:
            return self._error(request, "rejected", "precondition_failed", "receipt has no available reversal")
        if request.action != receipt.reverse_action:
            return self._error(request, "rejected", "invalid_request", "request does not name the receipt's reverse action")
        return self.execute(request)
