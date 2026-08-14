from collections import namedtuple

from apx.actions import ActionRegistry
from apx.bridges.psutil import PsutilBridge


class FakeProcess:
    info={"pid":12,"name":"python","username":"user","status":"running"}


class FakePsutil:
    @staticmethod
    def disk_usage(path): return namedtuple("Disk","total used free percent")(100,40,60,40)
    @staticmethod
    def process_iter(fields): return [FakeProcess()]
    @staticmethod
    def net_connections(kind):
        addr=namedtuple("Addr","ip port")("127.0.0.1",443)
        return [namedtuple("Connection","pid status laddr")(12,"LISTEN",addr)]


def test_optional_psutil_bridge_is_structured_bounded_and_replaceable():
    bridge=PsutilBridge(FakePsutil); registry=ActionRegistry(); bridge.register_actions(registry)
    assert bridge.disk_usage()["percent"]==40
    assert bridge.processes(1)["processes"][0]["name"]=="python"
    assert bridge.ports(443)["listeners"][0]["port"]==443
    assert {item.name for item in registry.list()}=={"machine.disk.usage","machine.process.list","machine.port.list"}


def test_missing_psutil_is_optional_not_core_failure():
    bridge=PsutilBridge(module=False)
    assert bridge.health().status=="unavailable"
