from __future__ import annotations

from apx import cli
from apx import setup


def _local_discovery():
    return {
        "hostname": "test-machine",
        "os": "Darwin",
        "architecture": "arm64",
        "capabilities": {"ssh": {"available": True}},
    }


def test_initialize_preserves_existing_config_when_remote_probe_fails(monkeypatch, tmp_path):
    destination = tmp_path / "config.toml"
    original = "version = 1\n\n[node]\nname = \"existing\"\n"
    destination.write_text(original)

    monkeypatch.setattr(setup, "inspect_host", lambda host: (
        _local_discovery()
        if host.transport == "local"
        else (_ for _ in ()).throw(RuntimeError("connection refused"))
    ))

    result = setup.initialize(
        destination,
        ssh_hosts=["vps=unreachable"],
        interactive=False,
        force=True,
    )

    assert result["written"] is False
    assert result["errors"] == [{
        "host": "vps",
        "target": "unreachable",
        "error": "connection refused",
    }]
    assert destination.read_text() == original


def test_initialize_writes_config_only_after_all_hosts_validate(monkeypatch, tmp_path):
    destination = tmp_path / "config.toml"

    def inspect(host):
        if host.transport == "local":
            return _local_discovery()
        return {"hostname": "vps", "os": "Linux", "architecture": "x86_64", "capabilities": {}}

    monkeypatch.setattr(setup, "inspect_host", inspect)
    result = setup.initialize(destination, ssh_hosts=["vps=vps"], interactive=False)

    assert result["written"] is True
    assert result["errors"] == []
    assert 'name = "vps"' in destination.read_text()


def test_cli_init_returns_failure_for_unreachable_host(monkeypatch, tmp_path, capsys):
    monkeypatch.setenv("APX_HOME", str(tmp_path / "home"))

    def inspect(host):
        if host.transport == "local":
            return _local_discovery()
        raise RuntimeError("connection refused")

    monkeypatch.setattr(setup, "inspect_host", inspect)
    result = cli._main(["init", "--non-interactive", "--json", "--host", "vps=unreachable"])

    assert result == 1
    assert '"written": false' in capsys.readouterr().out
    assert not (tmp_path / "home" / "config.toml").exists()
