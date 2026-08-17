# SPDX-License-Identifier: MPL-2.0
import tempfile
import unittest
from pathlib import Path

from apx import crypto, daemon
from apx.axp import ActionReceipt


class CryptoAndDaemonTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        self.home = Path(self.temp_dir.name) / ".config" / "apx"
        self.home.mkdir(parents=True, exist_ok=True)

    def test_canonical_json_and_digest(self):
        d1 = {"b": 2, "a": 1}
        d2 = {"a": 1, "b": 2}
        self.assertEqual(crypto.canonical_json_bytes(d1), crypto.canonical_json_bytes(d2))
        self.assertEqual(crypto.compute_receipt_digest(d1), crypto.compute_receipt_digest(d2))

    def test_sign_and_verify_receipt(self):
        raw = {
            "action": "host.status",
            "provider": "local",
            "actor": "human:operator",
            "status": "completed",
            "result": {"reachable": True},
            "timestamp": "2026-08-15T23:00:00Z"
        }
        signed = crypto.sign_receipt_dict(raw, node_name="mac", home_path=self.home)
        self.assertIn("signature", signed)
        self.assertIn("digest", signed)
        self.assertEqual(signed["signer_node"], "mac")
        self.assertTrue(crypto.verify_receipt_dict(signed, home_path=self.home))

        # Tampered result must fail verification
        tampered = dict(signed)
        tampered["result"] = {"reachable": False}
        self.assertFalse(crypto.verify_receipt_dict(tampered, home_path=self.home))

    def test_daemon_lifecycle(self):
        sock_path = daemon.daemon_socket_path(self.home)
        self.assertFalse(daemon.is_daemon_running(self.home))


if __name__ == "__main__":
    unittest.main()
