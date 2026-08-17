from __future__ import annotations

import json
import os
import platform
import re
import shutil
import socket
import subprocess
import sys
import tarfile
import tempfile
import uuid
from pathlib import Path
from typing import Any

import httpx
from platformdirs import user_config_dir

from . import __version__


CONFIG_DIR = Path(user_config_dir("apx"))
STATE_FILE = CONFIG_DIR / "management.json"
PORKBUN_BASE = "https://api.porkbun.com/api/json/v3"
OPENPOWER_UPDATE = "https://openpower.dev/apx/update.json"
GITHUB_RELEASE = "https://api.github.com/repos/JoshDeanPro/apx/releases/latest"


def read_payload() -> dict[str, Any]:
    try:
        raw = sys.stdin.read()
        return json.loads(raw) if raw.strip() else {}
    except Exception:
        return {}


def respond(data: Any, code: int = 0) -> None:
    print(json.dumps(data, ensure_ascii=False))
    raise SystemExit(code)


def load_state() -> dict[str, Any]:
    if not STATE_FILE.exists():
        return {
            "nicknames": {},
            "connections": [],
            "assignments": {},
            "service_settings": {},
            "prompts": [],
            "shared": {
                "automation_mode": "best-practice",
                "use_shared_settings": True,
            },
            "disabled_services": [],
        }

    try:
        data = json.loads(STATE_FILE.read_text())
    except Exception:
        data = {}

    data.setdefault("nicknames", {})
    data.setdefault("connections", [])
    data.setdefault("assignments", {})
    data.setdefault("service_settings", {})
    data.setdefault("prompts", [])
    data.setdefault("shared", {})
    data.setdefault("disabled_services", [])
    data["shared"].setdefault("automation_mode", "best-practice")
    data["shared"].setdefault("use_shared_settings", True)

    return data


def save_state(data: dict[str, Any]) -> None:
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    tmp = STATE_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=2))
    os.chmod(tmp, 0o600)
    os.replace(tmp, STATE_FILE)


def cli_json(args: list[str]) -> Any:
    cmd = [sys.executable, "-m", "apx", "--json", *args]

    p = subprocess.run(
        cmd,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=20,
    )

    if p.returncode != 0:
        return None

    text = p.stdout.strip()

    if not text:
        return None

    try:
        return json.loads(text)
    except Exception:
        pass

    for line in reversed(text.splitlines()):
        try:
            return json.loads(line)
        except Exception:
            continue

    return None


def cli_action(args: list[str]) -> bool:
    p = subprocess.run(
        [sys.executable, "-m", "apx", *args],
        text=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        timeout=30,
    )
    return p.returncode == 0


def dictionaries(obj: Any) -> list[dict[str, Any]]:
    found: list[dict[str, Any]] = []

    if isinstance(obj, dict):
        if any(k in obj for k in ("id", "name", "host", "service", "plugin")):
            found.append(obj)

        for value in obj.values():
            if isinstance(value, (dict, list)):
                found.extend(dictionaries(value))

    elif isinstance(obj, list):
        for value in obj:
            found.extend(dictionaries(value))

    return found


def identity(obj: dict[str, Any], fallback: str = "") -> str:
    for key in ("name", "id", "host", "service", "plugin", "title"):
        value = obj.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return fallback


def memory_gb() -> float | None:
    try:
        if sys.platform == "darwin":
            value = subprocess.check_output(
                ["sysctl", "-n", "hw.memsize"],
                text=True,
                stderr=subprocess.DEVNULL,
            ).strip()
            return round(int(value) / 1024**3, 1)

        if Path("/proc/meminfo").exists():
            text = Path("/proc/meminfo").read_text()
            match = re.search(r"MemTotal:\s+(\d+)", text)
            if match:
                return round(int(match.group(1)) / 1024**2, 1)
    except Exception:
        return None

    return None


def local_device() -> dict[str, Any]:
    state = load_state()
    system_name = socket.gethostname().split(".")[0]
    nickname = state["nicknames"].get(system_name)

    disk = shutil.disk_usage(Path.home())

    return {
        "id": system_name,
        "name": nickname or system_name,
        "nickname": nickname,
        "system_name": system_name,
        "local": True,
        "status": "Local",
        "health": {
            "state": "healthy",
            "label": "Online",
        },
        "os": platform.system(),
        "os_version": platform.mac_ver()[0] if sys.platform == "darwin" else platform.release(),
        "architecture": platform.machine(),
        "processor": platform.processor() or "Unknown",
        "memory_gb": memory_gb(),
        "storage_free_gb": round(disk.free / 1024**3, 1),
        "storage_total_gb": round(disk.total / 1024**3, 1),
        "apx_version": __version__,
        "protocol_version": "0.1",
        "localcloud": "Available",
    }


def devices() -> list[dict[str, Any]]:
    result = [local_device()]
    existing = {result[0]["id"]}

    raw = cli_json(["hosts"])

    for item in dictionaries(raw):
        name = identity(item)
        if not name or name in existing:
            continue

        existing.add(name)

        state = load_state()
        nickname = state["nicknames"].get(name)

        result.append(
            {
                "id": name,
                "name": nickname or name,
                "nickname": nickname,
                "system_name": name,
                "local": False,
                "status": item.get("status", "Configured"),
                "health": status_from_text(item.get("status", "Configured")),
                "raw": item,
            }
        )

    return result


def plugin_list() -> list[dict[str, Any]]:
    raw = cli_json(["plugins"])
    result: list[dict[str, Any]] = []
    seen: set[str] = set()

    for item in dictionaries(raw):
        name = identity(item)
        if not name or name in seen:
            continue

        seen.add(name)

        result.append(
            {
                "id": name,
                "name": name,
                "version": item.get("version"),
                "description": item.get("description", ""),
                "status": item.get("status") or item.get("health") or "Installed",
                "raw": item,
            }
        )

    return result


def services() -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    seen: set[str] = set()

    for host in devices():
        raw = cli_json(["services", host["system_name"]])

        for item in dictionaries(raw):
            name = identity(item)
            if not name or name in seen:
                continue

            seen.add(name)

            result.append(
                {
                    "id": name,
                    "name": name,
                    "host": host["id"],
                    "description": item.get("description", ""),
                    "status": item.get("status", "Available"),
                    "health": status_from_text(item.get("status", "Available")),
                    "raw": item,
                }
            )

    for plugin in plugin_list():
        name = plugin["name"]

        if name in seen:
            continue

        low = name.lower()

        if any(term in low for term in ("porkbun", "cloudflare", "purelymail")):
            seen.add(name)
            result.append(
                {
                    "id": name,
                    "name": name,
                    "host": None,
                    "description": plugin.get("description", ""),
                    "status": plugin.get("status", "Installed"),
                    "health": service_health(name),
                    "plugin": True,
                    "raw": plugin.get("raw", {}),
                }
            )

    for service in result:
        if service.get("health", {}).get("state") in {"neutral", None}:
            dynamic = service_health(service["id"])

            if dynamic.get("state") != "neutral":
                service["health"] = dynamic

    return result


def agents() -> list[dict[str, Any]]:
    raw = cli_json(["whoami"])
    found = dictionaries(raw)

    if not found:
        return [{
            "id": "local",
            "name": "Local user",
            "status": "Active",
            "health": {
                "state": "healthy",
                "label": "Active",
            },
        }]

    result = []

    for item in found:
        name = identity(item)
        if name:
            result.append(
                {
                    "id": name,
                    "name": name,
                    "status": "Active",
                    "health": {
                        "state": "healthy",
                        "label": "Active",
                    },
                    "raw": item,
                }
            )

    return result or [{"id": "local", "name": "Local user", "status": "Active"}]


def keychain_service(service: str) -> str:
    safe = re.sub(r"[^A-Za-z0-9_.-]", "-", service.lower())
    return f"dev.openpower.apx.{safe}"


def secret_get(service: str, field: str) -> str | None:
    if sys.platform != "darwin":
        return None

    p = subprocess.run(
        [
            "security",
            "find-generic-password",
            "-s",
            keychain_service(service),
            "-a",
            field,
            "-w",
        ],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
    )

    if p.returncode != 0:
        return None

    value = p.stdout.rstrip("\n")
    return value or None


def secret_set(service: str, field: str, value: str) -> None:
    if sys.platform != "darwin":
        raise RuntimeError("Secure credential storage is not available on this platform yet.")

    p = subprocess.run(
        [
            "security",
            "add-generic-password",
            "-U",
            "-s",
            keychain_service(service),
            "-a",
            field,
            "-w",
            value,
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
        text=True,
    )

    if p.returncode != 0:
        raise RuntimeError("The credential could not be saved securely.")


def secret_delete(service: str, field: str) -> None:
    if sys.platform != "darwin":
        return

    subprocess.run(
        [
            "security",
            "delete-generic-password",
            "-s",
            keychain_service(service),
            "-a",
            field,
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


def credential_fields(service: str) -> list[dict[str, str]]:
    low = service.lower()

    if "porkbun" in low:
        return [
            {"id": "api_key", "label": "API key"},
            {"id": "secret_api_key", "label": "Secret API key"},
        ]

    if "cloudflare" in low:
        return [{"id": "api_token", "label": "API token"}]

    if "purelymail" in low:
        return [
            {"id": "username", "label": "Username"},
            {"id": "api_token", "label": "API token"},
        ]

    return [{"id": "api_token", "label": "API token"}]


def credential_status(service: str) -> dict[str, Any]:
    fields = credential_fields(service)

    return {
        "service": service,
        "fields": [
            {
                **field,
                "configured": secret_get(service, field["id"]) is not None,
            }
            for field in fields
        ],
    }


def porkbun_headers() -> dict[str, str]:
    api = secret_get("porkbun", "api_key")
    secret = secret_get("porkbun", "secret_api_key")

    if not api or not secret:
        raise RuntimeError("Add your Porkbun API key and Secret API key first.")

    return {
        "X-API-Key": api,
        "X-Secret-API-Key": secret,
        "Accept": "application/json",
        "Content-Type": "application/json",
    }


def porkbun_request(
    method: str,
    endpoint: str,
    *,
    payload: dict[str, Any] | None = None,
    write: bool = False,
) -> dict[str, Any]:
    headers = porkbun_headers()

    if write:
        headers["Idempotency-Key"] = str(uuid.uuid4())

    with httpx.Client(timeout=20, follow_redirects=True) as client:
        response = client.request(
            method,
            f"{PORKBUN_BASE}/{endpoint.lstrip('/')}",
            headers=headers,
            json=payload,
        )

    try:
        data = response.json()
    except Exception:
        raise RuntimeError("Porkbun returned an unreadable response.")

    if response.status_code >= 400 or str(data.get("status", "")).upper() == "ERROR":
        message = data.get("message") or data.get("code") or "Porkbun rejected the request."
        raise RuntimeError(str(message))

    return data



def status_from_text(value: Any) -> dict[str, str]:
    text = str(value or "").strip()
    low = text.lower()

    if any(
        word in low
        for word in (
            "healthy",
            "working",
            "connected",
            "online",
            "active",
            "enabled",
            "configured",
            "local",
        )
    ):
        return {"state": "healthy", "label": text or "Working"}

    if any(
        word in low
        for word in (
            "starting",
            "connecting",
            "syncing",
            "pending",
        )
    ):
        return {"state": "progress", "label": text or "Working"}

    if any(
        word in low
        for word in (
            "failed",
            "error",
            "invalid",
            "unreachable",
            "denied",
        )
    ):
        return {"state": "failed", "label": text or "Unavailable"}

    if any(
        word in low
        for word in (
            "needs",
            "setup",
            "attention",
            "expired",
        )
    ):
        return {"state": "attention", "label": text or "Needs attention"}

    if any(
        word in low
        for word in (
            "disabled",
            "offline",
            "inactive",
            "not configured",
            "not connected",
        )
    ):
        return {"state": "inactive", "label": text or "Inactive"}

    return {"state": "neutral", "label": text or "Available"}


def service_health(service: str) -> dict[str, str]:
    state = load_state()

    if service in state.get("disabled_services", []):
        return {
            "state": "inactive",
            "label": "Disabled",
        }

    low = service.lower()

    if "porkbun" in low:
        api_key = secret_get("porkbun", "api_key")
        secret_key = secret_get("porkbun", "secret_api_key")

        if not api_key or not secret_key:
            return {
                "state": "attention",
                "label": "Needs credentials",
            }

        try:
            porkbun_request("GET", "ping")

            return {
                "state": "healthy",
                "label": "Connected",
            }
        except Exception as exc:
            message = str(exc).lower()

            if any(
                term in message
                for term in (
                    "auth",
                    "credential",
                    "key",
                    "unauthorized",
                    "forbidden",
                )
            ):
                return {
                    "state": "failed",
                    "label": "Authentication failed",
                }

            return {
                "state": "failed",
                "label": "Unreachable",
            }

    return {
        "state": "neutral",
        "label": "Available",
    }


def version_tuple(value: str) -> tuple[int, ...]:
    nums = re.findall(r"\d+", value.split("+")[0])
    return tuple(int(x) for x in nums[:4]) or (0,)


def update_check() -> dict[str, Any]:
    current = __version__
    latest = current
    minimum = None
    source_url = None

    try:
        with httpx.Client(timeout=1.8, follow_redirects=True) as client:
            r = client.get(OPENPOWER_UPDATE)

        if r.status_code == 200:
            data = r.json()
            latest = str(data.get("latest") or current)
            minimum = data.get("min_supported")
            source_url = data.get("source_url") or data.get("tarball_url")
    except Exception:
        pass

    if latest == current and source_url is None:
        try:
            with httpx.Client(timeout=2.5, follow_redirects=True) as client:
                r = client.get(
                    GITHUB_RELEASE,
                    headers={"Accept": "application/vnd.github+json"},
                )
                r.raise_for_status()
                data = r.json()

            latest = str(data.get("tag_name", current)).lstrip("v")
            source_url = data.get("tarball_url")
        except Exception:
            return {
                "current": current,
                "latest": current,
                "available": False,
                "mandatory": False,
                "offline": True,
            }

    available = version_tuple(latest) > version_tuple(current)

    mandatory = bool(
        minimum
        and version_tuple(current) < version_tuple(str(minimum))
    )

    return {
        "current": current,
        "latest": latest,
        "available": available,
        "mandatory": mandatory,
        "minimum": minimum,
        "source_url": source_url,
        "offline": False,
    }


def find_source_root(root: Path) -> Path:
    candidates = list(root.glob("*/pyproject.toml"))

    if candidates:
        return candidates[0].parent

    if (root / "pyproject.toml").exists():
        return root

    raise RuntimeError("The update package is incomplete.")


def run_checked(
    cmd: list[str],
    *,
    cwd: Path | None = None,
    env: dict[str, str] | None = None,
    timeout: int = 300,
) -> None:
    p = subprocess.run(
        cmd,
        cwd=str(cwd) if cwd else None,
        env=env,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=timeout,
    )

    if p.returncode != 0:
        detail = (p.stderr or p.stdout or "").strip().splitlines()
        last = detail[-1] if detail else "Unknown installation error"
        raise RuntimeError(last[:300])


def update_install(payload: dict[str, Any]) -> dict[str, Any]:
    check = update_check()

    if not check.get("available") and not check.get("mandatory"):
        return {
            "ok": True,
            "updated": False,
            "version": check["current"],
        }

    source_url = payload.get("source_url") or check.get("source_url")

    if not source_url:
        raise RuntimeError("The update is not ready for installation yet.")

    data_root = Path.home() / ".local" / "share" / "apx"
    runtime = Path(os.environ.get("APX_RUNTIME", str(data_root / "runtime")))
    ui_home = Path(os.environ.get("APX_UI_HOME", str(data_root / "ui")))

    runtime_next = data_root / "runtime-next"
    ui_next = data_root / "ui-next"
    runtime_prev = data_root / "runtime-previous"
    ui_prev = data_root / "ui-previous"

    shutil.rmtree(runtime_next, ignore_errors=True)
    shutil.rmtree(ui_next, ignore_errors=True)

    with tempfile.TemporaryDirectory(prefix="apx-update-") as temp:
        tempdir = Path(temp)
        archive = tempdir / "source.tar.gz"

        with httpx.Client(timeout=90, follow_redirects=True) as client:
            with client.stream("GET", source_url) as r:
                r.raise_for_status()

                with archive.open("wb") as f:
                    for chunk in r.iter_bytes():
                        f.write(chunk)

        extract = tempdir / "source"
        extract.mkdir()

        with tarfile.open(archive, "r:gz") as tf:
            try:
                tf.extractall(extract, filter="data")
            except TypeError:
                tf.extractall(extract)

        source = find_source_root(extract)

        if not (source / "ui" / "package.json").exists():
            raise RuntimeError(
                "This release predates the safe APX interface updater. "
                "It was not installed."
            )

        base_python = getattr(sys, "_base_executable", None) or sys.executable

        run_checked(
            [base_python, "-m", "venv", str(runtime_next)],
            timeout=120,
        )

        run_checked(
            [
                str(runtime_next / "bin" / "python"),
                "-m",
                "pip",
                "install",
                "--quiet",
                "--upgrade",
                "pip",
                "setuptools",
                "wheel",
            ],
            timeout=180,
        )

        run_checked(
            [
                str(runtime_next / "bin" / "python"),
                "-m",
                "pip",
                "install",
                "--quiet",
                str(source),
            ],
            timeout=300,
        )

        ui_source = source / "ui"

        if (ui_source / "package-lock.json").exists():
            run_checked(
                ["npm", "ci", "--silent"],
                cwd=ui_source,
                timeout=300,
            )
        else:
            run_checked(
                ["npm", "install", "--silent"],
                cwd=ui_source,
                timeout=300,
            )

        run_checked(
            ["npm", "run", "build", "--silent"],
            cwd=ui_source,
            timeout=180,
        )

        run_checked(
            [
                str(runtime_next / "bin" / "python"),
                "-c",
                "import apx, apx.cli, apx.ui_bridge; print(apx.__version__)",
            ],
            timeout=30,
        )

        shutil.copytree(
            ui_source,
            ui_next,
            ignore=shutil.ignore_patterns("src"),
        )

        smoke_env = os.environ.copy()
        smoke_env["APX_PYTHON"] = str(runtime_next / "bin" / "python")
        smoke_env["APX_RUNTIME"] = str(runtime_next)
        smoke_env["APX_UI_HOME"] = str(ui_next)

        run_checked(
            ["node", str(ui_next / "dist" / "index.mjs"), "--smoke"],
            env=smoke_env,
            timeout=30,
        )

    shutil.rmtree(runtime_prev, ignore_errors=True)
    shutil.rmtree(ui_prev, ignore_errors=True)

    runtime_moved = False
    ui_moved = False

    try:
        if runtime.exists():
            os.replace(runtime, runtime_prev)
            runtime_moved = True

        os.replace(runtime_next, runtime)

        if ui_home.exists():
            os.replace(ui_home, ui_prev)
            ui_moved = True

        os.replace(ui_next, ui_home)

    except Exception:
        if runtime.exists():
            shutil.rmtree(runtime, ignore_errors=True)

        if runtime_moved and runtime_prev.exists():
            os.replace(runtime_prev, runtime)

        if ui_home.exists():
            shutil.rmtree(ui_home, ignore_errors=True)

        if ui_moved and ui_prev.exists():
            os.replace(ui_prev, ui_home)

        raise RuntimeError(
            "The update could not be activated. "
            "Your previous APX installation was restored."
        )

    return {
        "ok": True,
        "updated": True,
        "version": check["latest"],
    }


def open_url(url: str) -> None:
    if sys.platform == "darwin":
        subprocess.Popen(
            ["open", url],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    elif sys.platform.startswith("linux"):
        subprocess.Popen(
            ["xdg-open", url],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )


def main() -> None:
    if len(sys.argv) < 2:
        respond({"ok": False, "error": "Missing bridge command."}, 2)

    command = sys.argv[1]
    payload = read_payload()

    try:
        if command == "info":
            respond(
                {
                    "ok": True,
                    "version": __version__,
                    "device": local_device(),
                }
            )

        if command == "devices":
            respond({"ok": True, "items": devices()})

        if command == "services":
            respond({"ok": True, "items": services()})

        if command == "plugins":
            respond({"ok": True, "items": plugin_list()})

        if command == "agents":
            respond({"ok": True, "items": agents()})

        if command == "state":
            respond({"ok": True, "state": load_state()})

        if command == "nickname-set":
            state = load_state()
            device = str(payload["device"])
            value = str(payload.get("value", "")).strip()

            if value:
                state["nicknames"][device] = value
            else:
                state["nicknames"].pop(device, None)

            save_state(state)
            respond({"ok": True})

        if command == "credential-status":
            respond(
                {
                    "ok": True,
                    **credential_status(str(payload["service"])),
                }
            )

        if command == "credential-set":
            service = str(payload["service"])
            field = str(payload["field"])
            value = str(payload.get("value", ""))

            if not value:
                raise RuntimeError("A value is required.")

            secret_set(service, field, value)
            respond({"ok": True})

        if command == "credential-delete":
            secret_delete(
                str(payload["service"]),
                str(payload["field"]),
            )
            respond({"ok": True})

        if command == "service-test":
            service = str(payload["service"])

            if "porkbun" in service.lower():
                data = porkbun_request("GET", "ping")
                respond(
                    {
                        "ok": True,
                        "message": "Porkbun credentials are working.",
                        "data": {
                            "yourIp": data.get("yourIp"),
                        },
                    }
                )

            respond(
                {
                    "ok": True,
                    "message": "Credentials are configured.",
                }
            )

        if command == "porkbun-domains":
            data = porkbun_request("GET", "domain/listAll")
            domains = data.get("domains") or []

            normalized = []

            for item in domains:
                if isinstance(item, str):
                    normalized.append({"domain": item})
                elif isinstance(item, dict):
                    normalized.append(item)

            respond({"ok": True, "items": normalized})

        if command == "porkbun-dns":
            domain = str(payload["domain"])
            data = porkbun_request("GET", f"dns/retrieve/{domain}")
            respond(
                {
                    "ok": True,
                    "items": data.get("records") or [],
                }
            )

        if command == "porkbun-dns-create":
            domain = str(payload["domain"])

            body = {
                "type": str(payload["type"]).upper(),
                "content": str(payload["content"]),
                "ttl": str(payload.get("ttl") or "600"),
                "name": str(payload.get("name") or ""),
                "dryRun": True,
            }

            porkbun_request(
                "POST",
                f"dns/create/{domain}",
                payload=body,
                write=True,
            )

            body.pop("dryRun", None)

            data = porkbun_request(
                "POST",
                f"dns/create/{domain}",
                payload=body,
                write=True,
            )

            respond({"ok": True, "data": data})

        if command == "porkbun-dns-delete":
            domain = str(payload["domain"])
            record_id = str(payload["id"])

            porkbun_request(
                "POST",
                f"dns/delete/{domain}/{record_id}",
                payload={"dryRun": True},
                write=True,
            )

            data = porkbun_request(
                "POST",
                f"dns/delete/{domain}/{record_id}",
                payload={},
                write=True,
            )

            respond({"ok": True, "data": data})

        if command == "connection-add":
            state = load_state()
            source = str(payload["source"])
            target = str(payload["target"])

            entry = {"source": source, "target": target}

            if entry not in state["connections"]:
                state["connections"].append(entry)

            save_state(state)
            respond({"ok": True})

        if command == "connection-remove":
            state = load_state()
            source = str(payload["source"])
            target = str(payload["target"])

            state["connections"] = [
                x
                for x in state["connections"]
                if not (
                    x.get("source") == source
                    and x.get("target") == target
                )
            ]

            save_state(state)
            respond({"ok": True})

        if command == "assignment-toggle":
            state = load_state()
            service = str(payload["service"])
            device = str(payload["device"])

            assigned = state["assignments"].setdefault(service, [])

            if device in assigned:
                assigned.remove(device)
                enabled = False
            else:
                assigned.append(device)
                enabled = True

            save_state(state)
            respond({"ok": True, "assigned": enabled})

        if command == "service-toggle":
            state = load_state()
            service = str(payload["service"])
            disabled = state["disabled_services"]

            if service in disabled:
                disabled.remove(service)
                enabled = True
                cli_action(["plugin", service])
            else:
                disabled.append(service)
                enabled = False

            save_state(state)
            respond({"ok": True, "enabled": enabled})

        if command == "shared-mode":
            state = load_state()
            state["shared"]["automation_mode"] = str(payload["mode"])
            save_state(state)
            respond({"ok": True})

        if command == "prompt-add":
            state = load_state()
            name = str(payload.get("name", "")).strip()
            content = str(payload.get("content", "")).strip()

            if not name or not content:
                raise RuntimeError("A name and prompt are required.")

            state["prompts"].append(
                {
                    "id": str(uuid.uuid4()),
                    "name": name,
                    "content": content,
                }
            )

            save_state(state)
            respond({"ok": True})

        if command == "prompt-delete":
            state = load_state()
            prompt_id = str(payload["id"])
            state["prompts"] = [
                x
                for x in state["prompts"]
                if x.get("id") != prompt_id
            ]
            save_state(state)
            respond({"ok": True})

        if command == "update-check":
            respond({"ok": True, **update_check()})

        if command == "update-install":
            respond(update_install(payload))

        if command == "open":
            open_url(str(payload["url"]))
            respond({"ok": True})

        raise RuntimeError("Unknown APX management operation.")

    except Exception as exc:
        respond(
            {
                "ok": False,
                "error": str(exc),
            },
            1,
        )


if __name__ == "__main__":
    main()
