from __future__ import annotations

import json
import os
import shlex
import shutil
import socket
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any

HOME = Path.home()

CONFIG_DIR = HOME / ".config" / "apx"
STATE_DIR = HOME / ".local" / "state" / "apx"

MACHINES_FILE = CONFIG_DIR / "machines.json"
NETWORK_FILE = STATE_DIR / "network.json"
STANDING_FILE = CONFIG_DIR / "standing-agents.json"
LINKS_FILE = CONFIG_DIR / "links.json"

DEFAULT_MACHINES = {
    "mbp": {
        "name": "MacBook",
        "local": True,
        "target": None,
        "role": "development",
    },
    "home": {
        "name": "Home",
        "local": False,
        "target": "home-eth",
        "role": "personal",
    },
    "vps": {
        "name": "VPS",
        "local": False,
        "target": "vps",
        "role": "production",
    },
}

PROBE = r'''
import json
import os
import pathlib
import shutil
import socket
import subprocess

home = pathlib.Path.home()

def find(name, extras=()):
    value = shutil.which(name)

    if value:
        return value

    for candidate in extras:
        path = pathlib.Path(candidate).expanduser()
        if path.exists() and os.access(path, os.X_OK):
            return str(path)

    return None

def version(path):
    if not path:
        return None

    try:
        p = subprocess.run(
            [path, "--version"],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            timeout=5,
            check=False,
        )
        return p.stdout.strip().splitlines()[0][:180]
    except Exception:
        return None

def count(pattern):
    try:
        p = subprocess.run(
            ["pgrep", "-fc", pattern],
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            timeout=3,
            check=False,
        )
        return int(p.stdout.strip() or "0")
    except Exception:
        return 0

def tmux_exists(name):
    tmux = shutil.which("tmux")
    if not tmux:
        return False

    p = subprocess.run(
        [tmux, "has-session", "-t", name],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        check=False,
    )

    return p.returncode == 0

apx = find(
    "apx",
    (
        home / ".local/bin/apx",
        home / ".local/share/apx/runtime/bin/apx",
        "/usr/local/bin/apx",
    ),
)

claude = find(
    "claude",
    (
        home / ".local/bin/claude",
        "/usr/local/bin/claude",
    ),
)

codex = find(
    "codex",
    (
        home / ".local/bin/codex",
        "/usr/local/bin/codex",
    ),
)

value = {
    "hostname": socket.gethostname(),
    "user": os.environ.get("USER") or os.environ.get("LOGNAME"),
    "home": str(home),
    "platform": os.uname().sysname,
    "architecture": os.uname().machine,
    "apx": {
        "installed": bool(apx),
        "path": apx,
        "version": version(apx),
    },
    "agents": {
        "claude": {
            "installed": bool(claude),
            "path": claude,
            "version": version(claude),
            "processes": count("[c]laude"),
            "standing_session": tmux_exists("apx-claude"),
        },
        "codex": {
            "installed": bool(codex),
            "path": codex,
            "version": version(codex),
            "processes": count("[c]odex"),
            "standing_session": tmux_exists("apx-codex"),
        },
    },
}

print(json.dumps(value))
'''


def load_json(path: Path, default: Any) -> Any:
    try:
        return json.loads(path.read_text())
    except Exception:
        return default


def save_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)

    tmp = path.with_suffix(path.suffix + ".tmp")

    tmp.write_text(
        json.dumps(value, indent=2) + "\n"
    )

    os.chmod(tmp, 0o600)
    tmp.replace(path)


def machine_config() -> dict[str, dict[str, Any]]:
    data = load_json(
        MACHINES_FILE,
        {},
    )

    if not isinstance(data, dict):
        data = {}

    result = dict(DEFAULT_MACHINES)

    for key, value in data.items():
        if isinstance(value, dict):
            merged = dict(
                result.get(key, {})
            )
            merged.update(value)
            result[key] = merged

    return result


def ensure_machine_config() -> None:
    if not MACHINES_FILE.exists():
        save_json(
            MACHINES_FILE,
            DEFAULT_MACHINES,
        )


def _local_probe() -> dict[str, Any]:
    scope: dict[str, Any] = {}
    exec(PROBE, scope)
    # PROBE prints; do a subprocess instead to capture cleanly.
    raise RuntimeError(
        "internal local probe fallback should not execute"
    )


def _run_probe(
    machine: str,
    config: dict[str, Any],
) -> dict[str, Any]:
    started = time.monotonic()

    try:
        if config.get("local"):
            command = [
                sys.executable,
                "-c",
                PROBE,
            ]
        else:
            target = config.get("target")

            if not target:
                raise RuntimeError(
                    "No transport target configured"
                )

            command = [
                "ssh",
                "-o",
                "BatchMode=yes",
                "-o",
                "ConnectTimeout=4",
                "-o",
                "ServerAliveInterval=3",
                "-o",
                "ServerAliveCountMax=1",
                target,
                "python3",
                "-c",
                shlex.quote(PROBE),
            ]

        p = subprocess.run(
            command,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=8,
            check=False,
        )

        latency = round(
            (time.monotonic() - started) * 1000,
            1,
        )

        if p.returncode != 0:
            return {
                "id": machine,
                "name": config.get(
                    "name",
                    machine,
                ),
                "role": config.get("role"),
                "online": False,
                "target": config.get("target"),
                "latency_ms": latency,
                "error": (
                    p.stderr.strip()
                    or p.stdout.strip()
                    or f"exit {p.returncode}"
                )[:300],
                "agents": {},
            }

        lines = [
            line
            for line in p.stdout.splitlines()
            if line.strip()
        ]

        if not lines:
            raise RuntimeError(
                "empty probe output"
            )

        value = json.loads(lines[-1])

        value.update(
            {
                "id": machine,
                "name": config.get(
                    "name",
                    machine,
                ),
                "role": config.get("role"),
                "online": True,
                "target": config.get("target"),
                "latency_ms": latency,
            }
        )

        return value

    except Exception as exc:
        return {
            "id": machine,
            "name": config.get(
                "name",
                machine,
            ),
            "role": config.get("role"),
            "online": False,
            "target": config.get("target"),
            "latency_ms": round(
                (time.monotonic() - started)
                * 1000,
                1,
            ),
            "error": str(exc)[:300],
            "agents": {},
        }


def refresh() -> dict[str, Any]:
    ensure_machine_config()

    config = machine_config()

    standing = load_json(
        STANDING_FILE,
        {},
    )

    if not isinstance(standing, dict):
        standing = {}

    machines = {}

    for machine, settings in config.items():
        value = _run_probe(
            machine,
            settings,
        )

        for agent, info in value.get(
            "agents",
            {},
        ).items():
            key = f"{machine}:{agent}"

            requested = bool(
                standing.get(key, {}).get(
                    "standing",
                    False,
                )
            )

            info["standing"] = requested

            if not value.get("online"):
                info["availability"] = "offline"
            elif not info.get("installed"):
                info["availability"] = "missing"
            elif info.get("processes", 0) > 0:
                info["availability"] = "running"
            else:
                info["availability"] = "ready"

        machines[machine] = value

    result = {
        "updated_at": (
            datetime.now()
            .astimezone()
            .isoformat()
        ),
        "controller": socket.gethostname(),
        "machines": machines,
    }

    save_json(
        NETWORK_FILE,
        result,
    )

    return result


def cached() -> dict[str, Any]:
    value = load_json(
        NETWORK_FILE,
        {},
    )

    if not isinstance(value, dict):
        return {
            "updated_at": None,
            "machines": {},
        }

    return value


def run_remote(
    machine: str,
    args: list[str],
    *,
    tty: bool = False,
) -> int:
    config = machine_config()

    if machine not in config:
        raise SystemExit(
            f"Unknown computer: {machine}"
        )

    settings = config[machine]

    if settings.get("local"):
        return subprocess.call(args)

    target = settings.get("target")

    if not target:
        raise SystemExit(
            f"No route to {machine}"
        )

    command = ["ssh"]

    if tty:
        command.append("-t")
    else:
        command.append("-n")

    command.extend(
        [
            "-o",
            "ConnectTimeout=6",
            target,
            "--",
            *args,
        ]
    )

    return subprocess.call(command)


def main(argv: list[str] | None = None) -> int:
    argv = list(
        sys.argv[1:]
        if argv is None
        else argv
    )

    command = (
        argv[0]
        if argv
        else "status"
    )

    args = argv[1:]

    if command == "refresh":
        value = refresh()

        print(
            json.dumps(
                value,
                indent=2,
            )
        )

        return 0

    if command in (
        "status",
        "show",
    ):
        print(
            json.dumps(
                cached(),
                indent=2,
            )
        )
        return 0

    if command == "remote":
        if not args:
            raise SystemExit(
                "Usage: apx network remote "
                "MACHINE -- COMMAND..."
            )

        machine = args[0]
        rest = args[1:]

        if rest and rest[0] == "--":
            rest = rest[1:]

        if not rest:
            raise SystemExit(
                "Missing remote command"
            )

        return run_remote(
            machine,
            rest,
            tty=False,
        )

    raise SystemExit(
        "Usage: apx network "
        "status|refresh|remote"
    )


if __name__ == "__main__":
    raise SystemExit(main())
