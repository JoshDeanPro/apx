from __future__ import annotations

from types import SimpleNamespace
from typing import Any, cast

import pytest

from apx.axp import ActionResult
from apx.actions import ActionRegistry
from apx.credentials import redact_public_value
from apx.events import EventRouter
from apx.files import normalized
from apx.httpserver import serve
from apx.plugins import PluginAPI, _ScopedPluginCloud
from apx.providers import ActionProvider, HTTPProviderAdapter


def test_public_redaction_covers_headers_urls_and_pem():
    value = redact_public_value({
        "authorization": "Bearer top-secret",
        "callback": "https://user:password@example.test/hook",
        "private_key": "-" * 5 + "BEGIN " + "PRIVATE KEY" + "-" * 5 + "secret" + "-" * 5 + "END " + "PRIVATE KEY" + "-" * 5,
        "message": "token=top-secret",
        "credential_id": "reference-only",
    })
    text = str(value)
    assert "top-secret" not in text
    assert "password" not in text
    assert "BEGIN PRIVATE KEY" not in text
    assert value["credential_id"] == "reference-only"


def test_http_action_results_are_minimum_disclosure():
    provider = ActionProvider("test", "test")
    result = ActionResult(
        action="test.read",
        ok=True,
        result={"summary": "ok", "api_key": "secret-value", "nested": {"cookie": "secret-cookie"}},
        execution={"argv": ["cat", "/private/path"]},
    )
    wire = HTTPProviderAdapter._public_wire(result)
    assert "api_key" not in wire["result"]
    assert "nested" not in wire["result"]
    assert "execution" not in wire


def test_plugin_credential_access_is_declared_and_scoped():
    secret = SimpleNamespace(reveal=lambda credential_id: {"value": credential_id})
    api = PluginAPI(
        actions=ActionRegistry(),
        events=EventRouter(),
        cloud=SimpleNamespace(secrets=secret),
        owner="external",
        allowed_credentials=("allowed",),
    )
    assert api.credential("allowed") == "allowed"
    with pytest.raises(PermissionError):
        api.credential("unrelated")


def test_external_plugin_cloud_uses_operator_scope_not_plugin_metadata():
    registry = SimpleNamespace(
        references={"operator-granted": object()},
        resolve=lambda credential_id: credential_id,
        health=lambda: [{"id": "operator-granted"}],
        redact=lambda value: value,
        redact_text=lambda value: value,
    )
    manager = SimpleNamespace(
        get=lambda credential_id: {"id": credential_id, "value": "<redacted>"},
        health=lambda credential_id: {"id": credential_id},
        reveal=lambda credential_id, caller_scope=None: {"id": credential_id, "value": "scoped"},
    )
    facade = _ScopedPluginCloud(cast(Any, SimpleNamespace(credentials=registry, secrets=manager)), ("operator-granted",))
    assert facade.credentials.health() == [{"id": "operator-granted"}]
    with pytest.raises(PermissionError):
        facade.secrets.reveal("plugin-guessed")


def test_protected_filesystem_targets_are_rejected():
    with pytest.raises(ValueError):
        normalized("~/.ssh/id_ed25519")
    with pytest.raises(ValueError):
        normalized("/tmp/service-account.pem")


def test_http_server_rejects_plaintext_remote_and_missing_token():
    with pytest.raises(ValueError, match="loopback-only"):
        serve(cast(Any, None), host="0.0.0.0")
    with pytest.raises(ValueError, match="APX_SERVER_TOKEN"):
        serve(cast(Any, None), host="127.0.0.1")
