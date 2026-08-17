# SPDX-License-Identifier: MPL-2.0
from apx.hardware import inspect_hardware, get_cpu_info, get_memory_info, get_accelerator_info


def test_hardware_inspection():
    hw = inspect_hardware()
    assert "cpu" in hw
    assert "memory" in hw
    assert "accelerators" in hw
    assert "compute_tier" in hw
    assert hw["compute_tier"] in ("workstation_heavy", "edge_capable", "lightweight_node")


def test_get_cpu_info():
    cpu = get_cpu_info()
    assert "model" in cpu
    assert "cores" in cpu
    assert "architecture" in cpu
    assert cpu["cores"] >= 1


def test_get_memory_info():
    mem = get_memory_info()
    assert "total_gb" in mem
    assert "available_gb" in mem
    assert mem["total_gb"] > 0


def test_get_accelerator_info():
    acc = get_accelerator_info()
    assert "metal" in acc
    assert "cuda" in acc
    assert "neural_engine" in acc

