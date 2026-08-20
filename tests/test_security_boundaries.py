from __future__ import annotations

import json
import os
import stat
from pathlib import Path

from apx.credentials import CredentialRegistry
from apx.http import HTTPClient
from apx.httpserver import CloudProviderView, make_handler
from apx.process import run
from apx.providers import ActionProvider, HTTPProviderAdapter
from apx.security import check


def test_security_check_flags_secret_values_and_public_bind(tmp_path: Path):
    config = tmp_path / "config.toml"
    config.write_text('[server]\nhost="0.0.0.0"\n[credentials.demo]\nsource="environment"\nvalue="do-not-store"\n')
    config.chmod(stat.S_IRUSR | stat.S_IWUSR)

    report = check(config)

    codes = {item["code"] for item in report["checks"]}
    assert "secret_in_config" in codes
    assert "public_bind" in codes
    assert report["ok"] is False
    assert "do-not-store" not in json.dumps(report)


def test_credential_redaction_covers_common_wire_forms(monkeypatch):
    monkeypatch.setenv("APX_TEST_TOKEN", "token-value")
    registry = CredentialRegistry.from_config({"service": {"reference": "APX_TEST_TOKEN"}})
    value = registry.redact({"authorization": "Bearer token-value", "cookie": "session=token-value", "url": "https://u:token-value@example.test"})

    assert "token-value" not in json.dumps(value)
    assert "<redacted>" in json.dumps(value)


def test_subprocess_does_not_inherit_unrelated_environment(monkeypatch):
    monkeypatch.setenv("APX_PRIVATE_TEST_TOKEN", "must-not-cross")
    result = run([os.environ.get("PYTHON", "python3"), "-c", "import os; print(os.getenv('APX_PRIVATE_TEST_TOKEN', 'absent'))"])
    assert result.stdout.strip() == "absent"


def test_public_manifest_does_not_expose_credentials_or_url_query():
    provider = ActionProvider("safe.test", "Safe", url="https://user:secret@example.test/apx?token=hidden", metadata={"version": "1", "api_key": "hidden"})
    public = provider.manifest().public_dict()
    encoded = json.dumps(public)
    assert "secret" not in encoded and "hidden" not in encoded
    assert "credential_required" not in encoded


def test_http_client_does_not_use_ambient_environment(monkeypatch):
    monkeypatch.setenv("HTTPS_PROXY", "http://user:secret@example.invalid:9")
    client = HTTPClient()
    assert client._client._trust_env is False
    client.close()
