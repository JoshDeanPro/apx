"""The live half of AXP <-> openpower.one: reports this machine and its
installed AI CLIs in (so the website's Devices/Agents pages actually
populate from a real running AXP instance, not an empty record a human has
to type in by hand), and polls for/executes commands a human dispatched
from the website.

Authenticates with this machine's own OpenPower identity token (from
`localcloud identity device-link`, stored via the credential system --
see auth_openpower.py for the token-acquisition side of this). Commands are
only ever executed through `cloud.run()`, which is the same policy-gated
dispatch every other AXP action goes through -- and only for actions in
_ALLOWED_ACTIONS, matching the identical allowlist openpower.one's own
routes/devices.py enforces server-side. Two independent enforcement points,
not one.
"""
from __future__ import annotations

import json
import platform
import shutil
import socket
import time
import urllib.error
import urllib.request
from typing import Any

from . import __version__ as AXP_VERSION
from .auth import AuthenticationError

# Binary name -> (display name, provider slug). Extend this dict to detect
# more -- detection is just "is this binary on PATH", nothing more invasive.
_KNOWN_AI_CLIS: dict[str, tuple[str, str]] = {
    "claude": ("Claude Code", "anthropic"),
    "codex": ("Codex CLI", "openai"),
    "gemini": ("Gemini CLI", "google"),
    "aider": ("Aider", "aider"),
    "cursor-agent": ("Cursor Agent", "cursor"),
    "opencode": ("OpenCode", "opencode"),
}

# Must match routes/devices.py's ALLOWED_COMMAND_ACTIONS on the API side --
# a second, independent enforcement point, not a substitute for the
# server-side check.
_ALLOWED_ACTIONS = {"service.status", "service.restart", "logs.read", "host.status"}


def detect_ai_clis() -> list[dict[str, str]]:
    detected = []
    for binary, (name, provider) in _KNOWN_AI_CLIS.items():
        if shutil.which(binary):
            detected.append({"name": name, "provider": provider})
    return detected


def _device_type() -> str:
    system = platform.system().lower()
    if system == "darwin":
        return "mac"
    if system == "linux":
        return "linux_server"
    if system == "windows":
        return "pc"
    return "other"


def _http_json(url: str, token: str, *, method: str = "GET", body: dict[str, Any] | None = None, timeout: int = 10) -> dict[str, Any]:
    data = json.dumps(body).encode() if body is not None else None
    request = urllib.request.Request(
        url,
        data=data,
        method=method,
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return json.loads(response.read() or b"{}")
    except urllib.error.HTTPError as error:
        try:
            detail = json.loads(error.read() or b"{}")
        except (ValueError, UnicodeDecodeError):
            detail = {}
        raise AuthenticationError(f"openpower.one returned {error.code}: {detail}") from error


def send_heartbeat(base_url: str, token: str, *, device_name: str | None = None) -> dict[str, Any]:
    """One heartbeat: reports this machine + its detected AI CLIs, returns
    {device_id, pending_commands}."""
    body = {
        "device_name": device_name or socket.gethostname(),
        "device_type": _device_type(),
        "buddy_os_version": AXP_VERSION,
        "axp_version": AXP_VERSION,
        "detected_agents": detect_ai_clis(),
    }
    return _http_json(f"{base_url.rstrip('/')}/v1/agent/heartbeat", token, method="POST", body=body)


def poll_commands(base_url: str, token: str) -> list[dict[str, Any]]:
    result = _http_json(f"{base_url.rstrip('/')}/v1/agent/commands", token)
    return result if isinstance(result, list) else []


def report_command_result(base_url: str, token: str, command_id: str, *, ok: bool, result: dict[str, Any] | None = None, error: str | None = None) -> None:
    _http_json(
        f"{base_url.rstrip('/')}/v1/agent/commands/{command_id}/result",
        token,
        method="POST",
        body={"status": "completed" if ok else "failed", "result": result, "error": error},
    )


def execute_command(cloud, command: dict[str, Any], *, actor: str) -> tuple[bool, dict[str, Any] | None, str | None]:
    """Runs one polled command through cloud.run() -- the same policy-gated
    dispatch every other AXP action uses -- if and only if its action is in
    the safe allowlist. Returns (ok, result, error)."""
    action = command.get("action")
    if action not in _ALLOWED_ACTIONS:
        return False, None, f"action {action!r} is not in the allowed remote-command set"
    params = command.get("params") or {}
    try:
        outcome = cloud.run(action, actor=actor, **params)
    except Exception as error:  # noqa: BLE001 - reported back as a command failure, not raised
        return False, None, str(error)
    if not outcome.ok:
        return False, None, str(outcome.error) if outcome.error else "action failed"
    return True, outcome.data if isinstance(outcome.data, dict) else {"data": outcome.data}, None


def run_once(cloud, base_url: str, token: str, *, actor: str) -> dict[str, Any]:
    """Single heartbeat + drain of currently-pending commands. What
    `localcloud openpower sync` runs; `localcloud openpower run` calls this
    in a loop."""
    heartbeat = send_heartbeat(base_url, token)
    commands = poll_commands(base_url, token)
    executed = []
    for command in commands:
        ok, result, error = execute_command(cloud, command, actor=actor)
        report_command_result(base_url, token, command["id"], ok=ok, result=result, error=error)
        executed.append({"id": command["id"], "action": command.get("action"), "ok": ok})
    return {"device_id": heartbeat.get("device_id"), "commands_executed": executed}


def run_loop(cloud, base_url: str, token: str, *, actor: str, interval: int = 30, on_tick=None) -> None:
    """Blocking loop: run_once every `interval` seconds. `on_tick(result)`
    is called after each cycle if given, for progress printing."""
    while True:
        result = run_once(cloud, base_url, token, actor=actor)
        if on_tick is not None:
            on_tick(result)
        time.sleep(interval)
