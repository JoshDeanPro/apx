# SPDX-License-Identifier: MPL-2.0
"""Reusable APX 0.1 provider/client conformance checks."""
from __future__ import annotations

from typing import Any
from jsonschema.validators import Draft202012Validator

from .client import APXClient
from .providers import ActionProvider, validate_provider


def provider_conformance(provider: ActionProvider) -> list[str]:
    errors = validate_provider(provider)
    for action in provider.actions:
        definition = action.definition()
        try:
            Draft202012Validator.check_schema(definition.input_schema)
            if definition.output_schema: Draft202012Validator.check_schema(definition.output_schema)
        except Exception as error:
            errors.append(f"{action.name}: invalid schema: {error}")
        if definition.retry == "idempotency_required" and not definition.idempotent:
            errors.append(f"{action.name}: idempotency_required retry requires idempotent=true")
        if definition.confirmation in {"transaction", "security_critical"} and action.prepare_handler is None:
            errors.append(f"{action.name}: strong confirmation requires prepare")
    return errors


def client_conformance(client: APXClient, *, read_action: str) -> list[str]:
    errors: list[str] = []
    manifest = client.discover()
    if manifest.apx_version != "0.1": errors.append("client accepted unsupported protocol")
    if read_action not in {action.id for action in manifest.actions}: errors.append("client did not discover read action")
    result = client.execute(read_action)
    if not result.ok or result.status != "completed": errors.append("client could not execute read action")
    return errors
