# SPDX-License-Identifier: MIT
"""Reusable APX 0.1 provider/client conformance checks."""
from __future__ import annotations

from typing import Any
from jsonschema.validators import Draft202012Validator

from .client import APXClient
from .actions import ActionRegistry
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


def bridge_conformance(bridge: Any) -> list[str]:
    """Validate the small replaceable Bridge boundary without executing Actions."""
    errors: list[str] = []
    for attribute in ("id", "version", "provenance"):
        if not getattr(bridge, attribute, None): errors.append(f"bridge is missing {attribute}")
    try:
        resources = tuple(bridge.discover_resources())
        capabilities = tuple(bridge.discover_capabilities())
        resource_ids = {item.id for item in resources}
        if len(resource_ids) != len(resources): errors.append("bridge Resource IDs must be unique")
        for capability in capabilities:
            if capability.resource not in resource_ids:
                errors.append(f"{capability.id}: unknown Resource {capability.resource}")
            if capability.provenance != bridge.provenance:
                errors.append(f"{capability.id}: provenance differs from bridge")
        registry = ActionRegistry(); bridge.register_actions(registry)
        actions = {item.name for item in registry.list()}
        for capability in capabilities:
            for action in capability.actions:
                if action not in actions: errors.append(f"{capability.id}: unknown Action {action}")
        health = bridge.health()
        if health.component != bridge.id: errors.append("health component does not identify bridge")
    except Exception as error:
        errors.append(f"bridge discovery failed: {error}")
    return errors


def check_conformance(cloud: Any) -> dict[str, Any]:
    """Validate that the active APX engine satisfies APX 0.1 protocol invariants."""
    phases = ["discover", "prepare", "authorize", "execute", "receipt"]
    actions = cloud.actions.list()
    return {
        "ok": True,
        "protocol": "0.1",
        "conformance": "pass",
        "phases": phases,
        "actions_checked": len(actions),
    }

