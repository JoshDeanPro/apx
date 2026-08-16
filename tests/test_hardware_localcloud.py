# SPDX-License-Identifier: MPL-2.0
import os
import tempfile
from pathlib import Path
from apx.hardware import inspect_hardware, get_cpu_info, get_memory_info, get_accelerator_info
from apx.localcloud import localcloud_status, localcloud_set, localcloud_get, _encrypt_payload, _decrypt_payload


def test_hardware_inspection():
    hw = inspect_hardware()
    assert "cpu" in hw
    assert "memory" in hw
    assert "accelerators" in hw
    assert "compute_tier" in hw
    assert hw["compute_tier"] in ("workstation_heavy", "edge_capable", "lightweight_node")


def test_localcloud_vault_encryption():
    test_data = {"api_key": "sk-test-12345", "nested": {"count": 42}}
    encrypted = _encrypt_payload(test_data)
    assert isinstance(encrypted, str)
    assert "sk-test-12345" not in encrypted  # Must be ciphertext

    decrypted = _decrypt_payload(encrypted)
    assert decrypted == test_data


def test_localcloud_set_get_flow():
    res = localcloud_set("test_key_xyz", "my_secret_token_abc")
    assert res["ok"] is True

    val = localcloud_get("test_key_xyz")
    assert val == "my_secret_token_abc"

    status = localcloud_status()
    assert status["status"] == "healthy"
    assert "Zero-Knowledge" in status["sovereignty"]
