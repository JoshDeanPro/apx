import json
import tempfile
import unittest
from pathlib import Path

from apx import APX, HTTPProviderAdapter
from apx.examples.subscriptions import build_reference_provider
from apx.providers import DISCOVERY_PATH


def config(tmp_path: Path) -> Path:
    path = tmp_path / "apx.toml"
    path.write_text('version=1\n[[hosts]]\nname="test"\ntransport="local"\n[[projects]]\nname="demo"\ndescription="demo"\n')
    return path


class FakeResponse:
    def __init__(self, data: bytes): self._data = data
    def read(self, size: int = -1) -> bytes: return self._data


def in_process_opener(adapter: HTTPProviderAdapter):
    def opener(request, timeout=10):
        status, _headers, body = adapter.handle("GET", DISCOVERY_PATH)
        assert status == 200
        return FakeResponse(json.dumps(body).encode())
    return opener


class AdapterConformanceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.cloud = APX(config(Path(self.temp.name)), plugins=False)
        self.actor = self.cloud.actors.resolve_default()

    def tearDown(self): self.temp.cleanup()

    def test_local_provider_conformance_passes_for_a_well_formed_provider(self):
        self.cloud.register_provider(build_reference_provider())
        result = self.cloud.run("adapter.test", actor=self.actor, provider="reference.local")
        self.assertTrue(result.ok, result.error)
        self.assertTrue(result.result["ok"])
        self.assertEqual(result.result["errors"], [])

    def test_unknown_provider_fails_cleanly(self):
        result = self.cloud.run("adapter.test", actor=self.actor, provider="no.such.provider")
        self.assertFalse(result.ok)

    def test_unknown_bridge_fails_cleanly(self):
        result = self.cloud.run("adapter.test", actor=self.actor, bridge="no-such-bridge")
        self.assertFalse(result.ok)

    def test_requires_exactly_one_target(self):
        result = self.cloud.run("adapter.test", actor=self.actor)
        self.assertFalse(result.ok)
        result = self.cloud.run("adapter.test", actor=self.actor, provider="a", bridge="b")
        self.assertFalse(result.ok)

    def test_remote_discovery_conformance_against_an_in_process_provider(self):
        from apx import adapter_test as adapter_test_module
        provider = build_reference_provider()
        adapter = HTTPProviderAdapter(provider, self.cloud.execute, self.cloud.prepare)
        result = adapter_test_module.test_remote("http://localhost", opener=in_process_opener(adapter))
        self.assertTrue(result["ok"], result["checks"])
        self.assertEqual(result["provider"], "reference.local")
        self.assertGreater(result["action_count"], 0)

    def test_remote_discovery_reports_failure_for_an_unreachable_origin(self):
        from apx import adapter_test as adapter_test_module
        def broken_opener(request, timeout=10): raise OSError("connection refused")
        result = adapter_test_module.test_remote("http://localhost", opener=broken_opener)
        self.assertFalse(result["ok"])
        self.assertFalse(result["checks"][0]["ok"])


if __name__ == "__main__":
    unittest.main()
