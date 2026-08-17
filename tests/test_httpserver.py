import json
import tempfile
import threading
import unittest
import urllib.request
from pathlib import Path

from apx import APX
from apx.httpserver import CloudProviderView, make_handler
from apx.providers import HTTPProviderAdapter
from http.server import ThreadingHTTPServer


def config(tmp_path: Path) -> Path:
    path = tmp_path / "apx.toml"
    path.write_text('version=1\n[[hosts]]\nname="test"\ntransport="local"\n[[projects]]\nname="demo"\ndescription="demo"\n')
    return path


class CloudProviderViewTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.cloud = APX(config(Path(self.temp.name)), plugins=False)

    def tearDown(self): self.temp.cleanup()

    def test_manifest_includes_every_registered_action(self):
        view = CloudProviderView(self.cloud, url="http://127.0.0.1:0")
        manifest = view.manifest()
        action_ids = {a.id for a in manifest.actions}
        self.assertEqual(action_ids, {a.name for a in self.cloud.actions.list()})

    def test_manifest_includes_real_resources(self):
        view = CloudProviderView(self.cloud)
        manifest = view.manifest()
        self.assertTrue(any(r.id == "host:test" for r in manifest.resources))

    def test_receipts_start_empty_and_are_gettable(self):
        view = CloudProviderView(self.cloud)
        self.assertIsNone(view.get_receipt("nope"))
        view.receipts["r1"] = "placeholder"
        self.assertEqual(view.get_receipt("r1"), "placeholder")


class HTTPServerLiveTests(unittest.TestCase):
    """Spins up a real server on an OS-assigned loopback port and drives it
    with real HTTP requests -- the same proof-of-real-behavior standard as the
    rest of this session, not a mocked handler."""

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.cloud = APX(config(Path(self.temp.name)), plugins=False)
        view = CloudProviderView(self.cloud, url="http://127.0.0.1:0")
        adapter = HTTPProviderAdapter(view, executor=self.cloud.execute, preparer=self.cloud.prepare)
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(adapter))
        self.port = self.server.server_address[1]
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))

    def tearDown(self):
        self.server.shutdown(); self.server.server_close(); self.thread.join(timeout=5)
        self.temp.cleanup()

    def _get(self, path):
        with self.opener.open(f"http://127.0.0.1:{self.port}{path}", timeout=5) as response:
            return response.status, json.loads(response.read())

    def _post(self, path, payload):
        data = json.dumps(payload).encode()
        request = urllib.request.Request(f"http://127.0.0.1:{self.port}{path}", data=data,
                                          headers={"Content-Type": "application/apx+json"}, method="POST")
        try:
            with self.opener.open(request, timeout=5) as response:
                return response.status, json.loads(response.read())
        except urllib.error.HTTPError as error:
            return error.code, json.loads(error.read())

    def test_discovery_endpoint_returns_a_real_manifest(self):
        status, payload = self._get("/.well-known/apx")
        self.assertEqual(status, 200)
        self.assertEqual(payload["provider"]["id"], "apx.local")
        self.assertGreater(len(payload["actions"]), 0)

    def test_execute_a_real_action_over_http(self):
        status, payload = self._post("/apx/actions/execute", {"apx": "0.1", "type": "action.request", "action": "host.list", "actor": "human:local"})
        self.assertEqual(status, 200)
        self.assertTrue(payload["ok"])
        self.assertEqual({h["name"] for h in payload["result"]["hosts"]}, {"test"})

    def test_unknown_action_returns_a_structured_error_not_a_crash(self):
        status, payload = self._post("/apx/actions/execute", {"apx": "0.1", "type": "action.request", "action": "not.a.real.action", "actor": "human:local"})
        self.assertNotEqual(status, 200)
        self.assertFalse(payload["ok"])

    def test_malformed_json_body_is_rejected_cleanly(self):
        request = urllib.request.Request(f"http://127.0.0.1:{self.port}/apx/actions/execute", data=b"{not json",
                                          headers={"Content-Type": "application/apx+json"}, method="POST")
        try:
            urllib.request.urlopen(request, timeout=5)
            self.fail("expected an HTTPError")
        except urllib.error.HTTPError as error:
            self.assertEqual(error.code, 400)


if __name__ == "__main__":
    unittest.main()
