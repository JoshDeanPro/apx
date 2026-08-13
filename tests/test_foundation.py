import json
import tempfile
import unittest
from pathlib import Path

import httpx

from apx.actions import ActionRegistry, RegisteredAction
from apx.files import atomic_write, bounded_read
from apx.foundation import COMPONENTS, inspect_foundation
from apx.http import HTTPClient, HTTPFailure, USER_AGENT
from apx.process import ProcessTimeout, run
from apx import APX


class FoundationTests(unittest.TestCase):
    def test_manifest_has_three_levels_and_capabilities(self):
        self.assertEqual({item.level for item in COMPONENTS},{"foundation","recommended","optional"})
        report=inspect_foundation()
        self.assertIn(report["platform"]["system"],{"Darwin","Linux","Windows"})
        self.assertTrue(all(item["capability"] for item in report["components"]))

    def test_atomic_write_preserves_complete_content_and_mode(self):
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/"state.json"
            atomic_write(path,'{"version": 1}\n')
            atomic_write(path,'{"version": 2}\n')
            self.assertEqual(json.loads(bounded_read(path)),{"version":2})
            self.assertEqual(path.stat().st_mode & 0o777,0o600)

    def test_process_is_bounded_and_shell_free(self):
        result=run(["python3","-c","print('x'*100)"],max_output_bytes=10)
        self.assertTrue(result.ok); self.assertTrue(result.truncated); self.assertEqual(len(result.stdout.encode()),10)
        with self.assertRaises(ProcessTimeout): run(["python3","-c","import time; time.sleep(2)"],timeout=0)

    def test_http_verified_https_limits_and_idempotent_retry(self):
        attempts=[]
        def handler(request):
            attempts.append(request)
            if len(attempts)==1: raise httpx.ConnectError("offline",request=request)
            return httpx.Response(200,json={"ok":True})
        client=HTTPClient(transport=httpx.MockTransport(handler))
        response=client.request("GET","https://example.test",retries=1)
        self.assertEqual(response.json(),{"ok":True}); self.assertEqual(len(attempts),2)
        self.assertEqual(attempts[-1].headers["user-agent"],USER_AGENT)
        with self.assertRaises(HTTPFailure): client.request("GET","http://example.test")

    def test_schema_is_checked_at_registration(self):
        registry=ActionRegistry()
        with self.assertRaises(Exception): registry.register(RegisteredAction("bad","bad",lambda:None,{"type":"not-a-json-schema-type"}))

    def test_secret_input_validation_error_never_echoes_value(self):
        with tempfile.TemporaryDirectory() as directory:
            config=Path(directory)/"apx.toml"; config.write_text('version=1\n[[hosts]]\nname="local"\ntransport="local"\n')
            cloud=APX(config,plugins=False)
            cloud.actions.register(RegisteredAction("secret.test","test",lambda secret: {},{"type":"object","properties":{"secret":{"type":"integer","x-apx-secret":True}},"required":["secret"]}))
            result=cloud.run("secret.test",secret="never-show-this")
            self.assertEqual(result.error.code,"invalid_input"); self.assertNotIn("never-show-this",str(result.to_dict()))


if __name__=="__main__": unittest.main()
