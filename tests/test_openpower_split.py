from __future__ import annotations


def test_openpower_localcloud_imports():
    from openpower.localcloud import LocalCloud
    from localcloud import LocalCloud as LegacyLocalCloud

    assert LocalCloud is LegacyLocalCloud


def test_apx_localcloud_is_compatibility_shim():
    from apx.localcloud import localcloud_status
    from openpower.localcloud import localcloud_status as owned_status

    assert localcloud_status is owned_status


def test_protocol_cli_rejects_localcloud_owned_commands(capsys):
    from apx.protocol_cli import main

    assert main(["localcloud", "status"]) == 2
    err = capsys.readouterr().err
    assert "moved to OpenPower LocalCloud" in err


def test_protocol_cli_bare_command_is_help(monkeypatch):
    from apx import protocol_cli

    seen = {}

    def fake_main(argv):
        seen["argv"] = argv
        return 0

    monkeypatch.setattr(protocol_cli.legacy_cli, "_main", fake_main)
    assert protocol_cli.main([]) == 0
    assert seen["argv"] == ["--help"]
