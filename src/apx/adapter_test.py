# SPDX-License-Identifier: MPL-2.0
"""`apx adapter test` / `adapter.test`: a conformance runner over the existing
provider/bridge validation primitives (providers.py's validate_provider/
RemoteProvider.discover, conformance.py's provider_conformance/bridge_conformance).

This does not invent new conformance rules -- it wires the ones that already exist
to something a business or developer can actually run against their own
implementation and get a pass/fail report from, per spec/conformance.md.
"""
from __future__ import annotations

from typing import Any

from jsonschema.validators import Draft202012Validator

from .axp import APX_PROTOCOL_VERSION
from .conformance import bridge_conformance, provider_conformance
from .providers import ActionProvider, RemoteProvider, validate_provider


class AdapterTestError(RuntimeError): pass


def _check(checks: list[dict[str, Any]], name: str, ok: bool, **extra: Any) -> None:
    checks.append({"check": name, "ok": ok, **{k: v for k, v in extra.items() if v is not None}})


def test_remote(origin: str, *, timeout: int = 10, opener: Any = None) -> dict[str, Any]:
    """Everything an independent, non-Python APX Provider implementation must get
    right to be usable: reachable discovery, a manifest that round-trips and passes
    validate_provider(), a supported protocol version, and schema-valid actions.
    `opener` is exposed only so tests can exercise this against an in-process
    HTTPProviderAdapter instead of a real socket -- see RemoteProvider.discover."""
    checks: list[dict[str, Any]] = []
    try:
        remote = RemoteProvider.discover(origin, timeout=timeout, opener=opener)
    except Exception as error:
        _check(checks, "discovery", False, error=str(error))
        return {"ok": False, "target": {"kind": "remote", "origin": origin}, "checks": checks}
    _check(checks, "discovery", True)
    manifest = remote.manifest()
    _check(checks, "apx_version", manifest.apx_version == APX_PROTOCOL_VERSION, value=manifest.apx_version)
    _check(checks, "has_actions", len(manifest.actions) > 0, count=len(manifest.actions))
    for action in manifest.actions:
        try:
            Draft202012Validator.check_schema(action.input_schema)
            if action.output_schema: Draft202012Validator.check_schema(action.output_schema)
            _check(checks, f"action_schema:{action.id}", True)
        except Exception as error:
            _check(checks, f"action_schema:{action.id}", False, error=str(error))
        if action.reversible and not action.reverse_action:
            _check(checks, f"reversible_declares_reverse_action:{action.id}", False)
        if action.retry == "idempotency_required" and not action.idempotent:
            _check(checks, f"idempotency_consistency:{action.id}", False)
    return {"ok": all(c["ok"] for c in checks), "target": {"kind": "remote", "origin": origin},
            "apx_version": manifest.apx_version, "provider": manifest.provider.id, "action_count": len(manifest.actions),
            "checks": checks}


def test_local_provider(provider: ActionProvider) -> dict[str, Any]:
    errors = provider_conformance(provider)
    return {"ok": not errors, "target": {"kind": "provider", "id": provider.identity.id}, "errors": errors,
            "checks": [{"check": "provider_conformance", "ok": not errors, "errors": errors}]}


def test_manifest(manifest: Any) -> dict[str, Any]:
    errors = validate_provider(manifest)
    return {"ok": not errors, "target": {"kind": "manifest", "provider": manifest.provider.id}, "errors": errors,
            "checks": [{"check": "manifest_conformance", "ok": not errors, "errors": errors}]}


def test_bridge(bridge: Any) -> dict[str, Any]:
    errors = bridge_conformance(bridge)
    return {"ok": not errors, "target": {"kind": "bridge", "id": bridge.id}, "errors": errors,
            "checks": [{"check": "bridge_conformance", "ok": not errors, "errors": errors}]}


def run(cloud: Any, *, url: str | None = None, provider: str | None = None, bridge: str | None = None,
        timeout: int = 10, opener: Any = None) -> dict[str, Any]:
    given = [name for name, value in (("url", url), ("provider", provider), ("bridge", bridge)) if value]
    if len(given) != 1:
        raise AdapterTestError("adapter.test requires exactly one of: url, provider, bridge")
    if url: return test_remote(url, timeout=timeout, opener=opener)
    if provider:
        target = cloud.providers.get(provider)
        if target is None: raise AdapterTestError(f"unknown provider {provider!r}")
        return test_local_provider(target) if isinstance(target, ActionProvider) else test_manifest(target.manifest())
    target = cloud.bridges.get(bridge)
    if target is None: raise AdapterTestError(f"unknown bridge {bridge!r}")
    return test_bridge(target)
