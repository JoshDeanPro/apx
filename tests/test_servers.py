from __future__ import annotations

from pathlib import Path

from apx import APX
from apx.providers import ActionProvider
from apx.tui import TUIEngine


def config(tmp_path: Path) -> Path:
    path = tmp_path / "apx.toml"
    path.write_text('version=1\n[[hosts]]\nname="local"\ntransport="local"\n')
    return path


def provider() -> ActionProvider:
    value = ActionProvider("server.test", "Test Server", url="https://user:secret@example.test/apx", metadata={"version": "2.4.1"})

    @value.action("server.read", description="Read server data", idempotent=True)
    def read():
        return {"ok": True}

    @value.action("server.pending", description="Temporarily unavailable", available=False, idempotent=True)
    def pending():
        return {"ok": False}

    return value


def test_server_list_is_read_only_and_secret_free(tmp_path):
    cloud = APX(config(tmp_path), plugins=False)
    cloud.register_provider(provider())

    result = cloud.run("server.list")

    assert result.ok
    item = result.result["servers"][0]
    assert item["id"] == "server.test"
    assert item["endpoint"] == "https://example.test/apx"
    assert "secret" not in str(item)
    assert item["protocol_version"] == "0.1"
    assert item["implementation_version"] == "2.4.1"
    assert item["action_count"] == 2
    assert item["unavailable_actions"] == ["server.pending"]


def test_server_inspect_and_status_are_scoped_to_one_provider(tmp_path):
    cloud = APX(config(tmp_path), plugins=False)
    cloud.register_provider(provider())

    inspected = cloud.run("server.inspect", server="server.test")
    status = cloud.run("server.status", server="server.test")

    assert inspected.ok and status.ok
    assert inspected.result["id"] == status.result["id"] == "server.test"
    assert inspected.result["health"]["status"] == "healthy"

    missing = cloud.run("server.inspect", server="missing")
    assert not missing.ok
    assert missing.error is not None
    assert "missing" in missing.error.message


def test_tui_server_screen_uses_live_inventory_state(tmp_path):
    cloud = APX(config(tmp_path), plugins=False)
    cloud.register_provider(provider())
    engine = TUIEngine(cloud, actor="human:local")

    items = engine.create_servers_screen().get_items()

    assert len(items) == 1
    assert items[0].title == "Test Server"
    assert items[0].tag == "HEALTHY"
    assert "2 actions" in items[0].subtitle
    assert "secret" not in str(items[0].data)
