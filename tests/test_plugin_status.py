from __future__ import annotations

from pathlib import Path

from apx import APX


def config(tmp_path: Path, extra: str = "") -> Path:
    path = tmp_path / "apx.toml"
    path.write_text('version=1\n[[hosts]]\nname="local"\ntransport="local"\n' + extra)
    return path


def test_available_unconfigured_plugin_is_not_active(tmp_path):
    cloud = APX(config(tmp_path), plugins=True)
    status = cloud.plugin_manager.status("cloudflare")

    assert status.available is True
    assert status.installed is True
    assert status.enabled is False
    assert status.configured is False
    assert status.active is False
    assert status.state == "disabled"


def test_enabled_plugin_missing_credential_is_not_active(tmp_path):
    cloud = APX(config(tmp_path, '[plugins.cloudflare]\nenabled=true\ncredential="cf"\n'), plugins=True)
    status = cloud.plugin_manager.status("cloudflare")

    assert status.enabled is True
    assert status.configured is True
    assert status.credential_ready is False
    assert status.active is False
    assert status.state == "credentials_required"


def test_enabled_plugin_load_failure_is_not_active(tmp_path):
    cloud = APX(config(tmp_path, '[plugins.openai]\nenabled=true\n'), plugins=True)
    cloud.plugin_manager.health.append({"name": "openai", "ok": False, "error": "provider setup failed"})
    status = cloud.plugin_manager.status("openai")

    assert status.enabled is True
    assert status.configured is True
    assert status.healthy is False
    assert status.active is False
    assert status.state == "unhealthy"


def test_loaded_configured_healthy_plugin_is_active(tmp_path):
    cloud = APX(config(tmp_path, '[plugins.drift]\nenabled=true\n'), plugins=True)
    status = cloud.plugin_manager.status("drift")

    assert status.available is True
    assert status.installed is True
    assert status.enabled is True
    assert status.configured is True
    assert status.credential_ready is True
    assert status.healthy is True
    assert status.active is True
    assert status.state == "active"
