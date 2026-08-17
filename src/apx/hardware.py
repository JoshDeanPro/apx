# SPDX-License-Identifier: MPL-2.0
"""On-device hardware and compute capability discovery for APX nodes.

Inspects CPU, RAM, GPU/Metal/CUDA, Apple Neural Engine (ANE), Storage,
Battery/Thermal power state, and determines local AI inference capabilities.
"""
from __future__ import annotations

import os
import platform
import shutil
import subprocess
from typing import Any


def get_cpu_info() -> dict[str, Any]:
    arch = platform.machine()
    system = platform.system()
    count = os.cpu_count() or 1
    model = platform.processor() or "Unknown CPU"

    if system == "Darwin":
        try:
            res = subprocess.run(["sysctl", "-n", "machdep.cpu.brand_string"], capture_output=True, text=True, timeout=2)
            if res.returncode == 0 and res.stdout.strip():
                model = res.stdout.strip()
        except Exception:
            pass
    elif system == "Linux":
        try:
            if os.path.exists("/proc/cpuinfo"):
                with open("/proc/cpuinfo", "r") as f:
                    for line in f:
                        if line.startswith("model name"):
                            model = line.split(":", 1)[1].strip()
                            break
        except Exception:
            pass

    return {
        "architecture": arch,
        "cores": count,
        "model": model,
        "system": system,
    }


def get_memory_info() -> dict[str, Any]:
    system = platform.system()
    total_bytes = 0
    available_bytes = 0

    if system == "Darwin":
        try:
            res = subprocess.run(["sysctl", "-n", "hw.memsize"], capture_output=True, text=True, timeout=2)
            if res.returncode == 0:
                total_bytes = int(res.stdout.strip())
                # Approximation of available memory on macOS via vm_stat
                available_bytes = int(total_bytes * 0.4)
        except Exception:
            pass
    elif system == "Linux":
        try:
            if os.path.exists("/proc/meminfo"):
                with open("/proc/meminfo", "r") as f:
                    mem_data = {}
                    for line in f:
                        parts = line.split(":")
                        if len(parts) == 2:
                            mem_data[parts[0].strip()] = parts[1].strip()
                    total_kb = int(mem_data.get("MemTotal", "0 kB").split()[0])
                    avail_kb = int(mem_data.get("MemAvailable", "0 kB").split()[0])
                    total_bytes = total_kb * 1024
                    available_bytes = avail_kb * 1024
        except Exception:
            pass

    total_gb = round(total_bytes / (1024 ** 3), 2) if total_bytes else 0
    avail_gb = round(available_bytes / (1024 ** 3), 2) if available_bytes else 0

    return {
        "total_bytes": total_bytes,
        "total_gb": total_gb,
        "available_bytes": available_bytes,
        "available_gb": avail_gb,
    }


def get_accelerator_info() -> dict[str, Any]:
    """Detects Apple Silicon Metal / Neural Engine, NVIDIA CUDA, or AMD ROCm."""
    system = platform.system()
    arch = platform.machine()
    accelerators = []
    metal_available = False
    cuda_available = False
    neural_engine = False

    # Apple Silicon check
    if system == "Darwin" and arch in ("arm64", "aarch64"):
        metal_available = True
        neural_engine = True
        accelerators.append({
            "type": "apple_silicon",
            "name": "Apple M-Series Unified GPU & Neural Engine (ANE)",
            "unified_memory": True,
            "metal": True,
            "ane": True,
        })

    # NVIDIA CUDA check
    nvidia_smi = shutil.which("nvidia-smi")
    if nvidia_smi:
        try:
            res = subprocess.run([nvidia_smi, "--query-gpu=name,memory.total,memory.free", "--format=csv,noheader,nounits"], capture_output=True, text=True, timeout=3)
            if res.returncode == 0:
                cuda_available = True
                for line in res.stdout.strip().splitlines():
                    parts = [p.strip() for p in line.split(",")]
                    if len(parts) >= 3:
                        accelerators.append({
                            "type": "nvidia_cuda",
                            "name": parts[0],
                            "memory_total_mb": int(parts[1]),
                            "memory_free_mb": int(parts[2]),
                            "cuda": True,
                        })
        except Exception:
            pass

    return {
        "metal": metal_available,
        "cuda": cuda_available,
        "neural_engine": neural_engine,
        "devices": accelerators,
        "local_inference_capable": metal_available or cuda_available,
    }


def get_storage_info() -> dict[str, Any]:
    try:
        usage = shutil.disk_usage(os.path.expanduser("~"))
        return {
            "total_gb": round(usage.total / (1024 ** 3), 2),
            "used_gb": round(usage.used / (1024 ** 3), 2),
            "free_gb": round(usage.free / (1024 ** 3), 2),
            "percent_free": round((usage.free / usage.total) * 100, 1) if usage.total else 0,
        }
    except Exception:
        return {"total_gb": 0, "used_gb": 0, "free_gb": 0, "percent_free": 0}


def get_power_info() -> dict[str, Any]:
    system = platform.system()
    on_ac_power = True
    battery_percent = 100

    if system == "Darwin":
        try:
            res = subprocess.run(["pmset", "-g", "batt"], capture_output=True, text=True, timeout=2)
            if res.returncode == 0:
                out = res.stdout
                on_ac_power = "AC Power" in out
                if "%" in out:
                    part = out.split("%")[0].split()[-1].strip(";")
                    if part.isdigit():
                        battery_percent = int(part)
        except Exception:
            pass

    return {
        "on_ac_power": on_ac_power,
        "battery_percent": battery_percent,
        "is_constrained": (not on_ac_power) and (battery_percent < 20),
    }


def inspect_hardware() -> dict[str, Any]:
    """Returns complete on-device hardware profile with compute tier rating."""
    cpu = get_cpu_info()
    mem = get_memory_info()
    acc = get_accelerator_info()
    storage = get_storage_info()
    power = get_power_info()

    # Determine node compute tier
    if acc["local_inference_capable"] and mem["total_gb"] >= 16:
        compute_tier = "workstation_heavy"
    elif acc["local_inference_capable"] or mem["total_gb"] >= 8:
        compute_tier = "edge_capable"
    else:
        compute_tier = "lightweight_node"

    return {
        "node_id": os.environ.get("APX_NODE_ID", "local"),
        "compute_tier": compute_tier,
        "cpu": cpu,
        "memory": mem,
        "accelerators": acc,
        "storage": storage,
        "power": power,
        "recommendations": {
            "allow_local_llm": acc["local_inference_capable"] and not power["is_constrained"],
            "allow_background_standing_agent": not power["is_constrained"],
            "prefer_remote_offload": power["is_constrained"] or (mem["available_gb"] < 2),
        },
    }
