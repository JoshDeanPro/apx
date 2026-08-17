from __future__ import annotations

import json
import os
import plistlib
import shutil
import socket
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

from .ui_bridge import load_state, save_state

LABEL = "dev.openpower.apx.server"
PORT = 8420


def local_id() -> str:
    return socket.gethostname().split(".")[0]


def role(device: str | None = None) -> str:
    state = load_state()
    return str(
        state.get("device_modes", {}).get(
            device or local_id(),
            "client",
        )
    )


def save_role(device: str, value: str) -> None:
    state = load_state()
    state.setdefault("device_modes", {})[device] = value
    save_state(state)


def launch_target() -> str:
    return f"gui/{os.getuid()}/{LABEL}"


def plist_path() -> Path:
    return (
        Path.home()
        / "Library"
        / "LaunchAgents"
        / f"{LABEL}.plist"
    )


def mac_status() -> bool:
    result = subprocess.run(
        ["launchctl", "print", launch_target()],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    return result.returncode == 0


def linux_unit_path() -> Path:
    return (
        Path.home()
        / ".config"
        / "systemd"
        / "user"
        / "apx-server.service"
    )


def linux_status() -> bool:
    if not shutil.which("systemctl"):
        return False

    result = subprocess.run(
        [
            "systemctl",
            "--user",
            "is-active",
            "--quiet",
            "apx-server.service",
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    return result.returncode == 0


def server_status() -> dict[str, Any]:
    if sys.platform == "darwin":
        active = mac_status()
        supported = True
    elif sys.platform.startswith("linux") and shutil.which("systemctl"):
        active = linux_status()
        supported = True
    else:
        active = False
        supported = False

    return {
        "active": active,
        "supported": supported,
        "health": {
            "state": "healthy" if active else "inactive",
            "label": "Running" if active else "Stopped",
        },
    }


def start_server() -> dict[str, Any]:
    data_dir = Path.home() / ".local" / "share" / "apx"
    log_dir = data_dir / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)

    if sys.platform == "darwin":
        path = plist_path()
        path.parent.mkdir(parents=True, exist_ok=True)

        payload = {
            "Label": LABEL,
            "ProgramArguments": [
                sys.executable,
                "-m",
                "apx",
                "serve",
                "--host",
                "127.0.0.1",
                "--port",
                str(PORT),
            ],
            "RunAtLoad": True,
            "KeepAlive": True,
            "ProcessType": "Background",
            "StandardOutPath": str(log_dir / "server.log"),
            "StandardErrorPath": str(log_dir / "server-error.log"),
        }

        with path.open("wb") as handle:
            plistlib.dump(payload, handle)

        subprocess.run(
            ["launchctl", "bootout", launch_target()],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )

        result = subprocess.run(
            [
                "launchctl",
                "bootstrap",
                f"gui/{os.getuid()}",
                str(path),
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )

        if result.returncode != 0:
            raise RuntimeError("APX Server could not start.")

    elif sys.platform.startswith("linux") and shutil.which("systemctl"):
        path = linux_unit_path()
        path.parent.mkdir(parents=True, exist_ok=True)

        path.write_text(
            "\n".join(
                [
                    "[Unit]",
                    "Description=APX Server",
                    "",
                    "[Service]",
                    f"ExecStart={sys.executable} -m apx serve --host 127.0.0.1 --port {PORT}",
                    "Restart=on-failure",
                    "",
                    "[Install]",
                    "WantedBy=default.target",
                    "",
                ]
            )
        )

        subprocess.run(
            ["systemctl", "--user", "daemon-reload"],
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )

        subprocess.run(
            ["systemctl", "--user", "enable", "--now", "apx-server.service"],
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )

    else:
        raise RuntimeError("Background APX Server is not supported on this system yet.")

    time.sleep(0.4)

    status = server_status()

    if not status["active"]:
        raise RuntimeError("APX Server stopped during startup.")

    return status


def stop_server() -> dict[str, Any]:
    if sys.platform == "darwin":
        subprocess.run(
            ["launchctl", "bootout", launch_target()],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )

        try:
            plist_path().unlink()
        except FileNotFoundError:
            pass

    elif sys.platform.startswith("linux") and shutil.which("systemctl"):
        subprocess.run(
            ["systemctl", "--user", "disable", "--now", "apx-server.service"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )

    return server_status()


def set_role(device: str | None, value: str) -> dict[str, Any]:
    value = value.lower()
    device = device or local_id()

    if value not in {"client", "mesh", "server"}:
        raise RuntimeError("Choose Client, Mesh or Server.")

    if device != local_id():
        raise RuntimeError("Connect to that device before changing its role.")

    save_role(device, value)

    if value in {"server", "mesh"}:
        server = start_server()
    else:
        server = stop_server()

    return {
        "device": device,
        "mode": value,
        "server": server,
    }


def background_enabled() -> bool:
    state = load_state()
    return bool(state.get("background_enabled", False))


def set_background(enabled: bool) -> dict[str, Any]:
    state = load_state()
    state["background_enabled"] = enabled
    save_state(state)

    if not enabled:
        status = stop_server()
    elif role() in {"server", "mesh"}:
        status = start_server()
    else:
        status = server_status()

    return {
        "enabled": enabled,
        "mode": role(),
        "server": status,
    }


def read_payload() -> dict[str, Any]:
    raw = sys.stdin.read()
    if not raw.strip():
        return {}
    return json.loads(raw)


def respond(payload: dict[str, Any], code: int = 0) -> None:
    print(json.dumps(payload))
    raise SystemExit(code)


def main() -> None:
    if len(sys.argv) < 2:
        respond({"ok": False, "error": "Missing operation."}, 2)

    command = sys.argv[1]
    payload = read_payload()

    try:
        if command == "device-mode-get":
            device = payload.get("device") or local_id()
            respond(
                {
                    "ok": True,
                    "device": device,
                    "mode": role(device),
                    "server": server_status(),
                }
            )

        if command == "device-mode-set":
            respond(
                {
                    "ok": True,
                    **set_role(
                        payload.get("device"),
                        str(payload.get("mode", "client")),
                    ),
                }
            )

        if command == "background-status":
            respond(
                {
                    "ok": True,
                    "enabled": background_enabled(),
                    "mode": role(),
                    "server": server_status(),
                }
            )

        if command == "background-set":
            respond(
                {
                    "ok": True,
                    **set_background(bool(payload.get("enabled"))),
                }
            )

        if command == "server-status":
            respond({"ok": True, **server_status()})

        raise RuntimeError("Unknown APX device operation.")

    except Exception as exc:
        respond({"ok": False, "error": str(exc)}, 1)


if __name__ == "__main__":
    main()
