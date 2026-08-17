# SPDX-License-Identifier: MIT
"""APX Unix Domain Socket Daemon (`apxd`) for ultra-low latency (<2ms) local action dispatch."""
from __future__ import annotations

import json
import os
import signal
import socket
import sys
import threading
import time
from pathlib import Path
from typing import Any

from .config import apx_home, default_config_path


def daemon_socket_path(home_path: Path | None = None) -> Path:
    base = home_path or apx_home()
    return base / "apx.sock"


def daemon_pid_path(home_path: Path | None = None) -> Path:
    base = home_path or apx_home()
    return base / "apxd.pid"


def is_daemon_running(home_path: Path | None = None) -> bool:
    sock = daemon_socket_path(home_path)
    if not sock.exists():
        return False
    try:
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as client:
            client.settimeout(0.5)
            client.connect(str(sock))
            client.sendall(json.dumps({"method": "ping"}).encode("utf-8") + b"\n")
            data = client.recv(1024)
            return bool(data and b"pong" in data)
    except (OSError, socket.timeout):
        return False


def send_daemon_request(payload: dict[str, Any], timeout: float = 30.0, home_path: Path | None = None) -> dict[str, Any] | None:
    sock = daemon_socket_path(home_path)
    if not sock.exists():
        return None
    try:
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as client:
            client.settimeout(timeout)
            client.connect(str(sock))
            client.sendall(json.dumps(payload).encode("utf-8") + b"\n")
            buffer = b""
            while True:
                chunk = client.recv(4096)
                if not chunk:
                    break
                buffer += chunk
                if buffer.endswith(b"\n"):
                    break
            if not buffer:
                return None
            return json.loads(buffer.decode("utf-8").strip())
    except Exception:
        return None


class APXDaemon:
    def __init__(self, config_path: str | Path | None = None) -> None:
        self.config_path = Path(config_path).expanduser() if config_path else default_config_path()
        self.home = apx_home()
        self.sock_path = daemon_socket_path(self.home)
        self.pid_path = daemon_pid_path(self.home)
        self._running = False
        self._server_sock: socket.socket | None = None
        self._cloud: Any = None

    def _get_cloud(self) -> Any:
        if self._cloud is None:
            from .cloud import APX
            self._cloud = APX(str(self.config_path) if self.config_path.exists() else None)
        return self._cloud

    def handle_client(self, conn: socket.socket) -> None:
        try:
            conn.settimeout(30.0)
            data = conn.recv(65536)
            if not data:
                return
            req = json.loads(data.decode("utf-8").strip())
            method = req.get("method")
            params = req.get("params", {})

            if method == "ping":
                resp = {"ok": True, "result": "pong", "time": time.time()}
            elif method == "status":
                resp = {"ok": True, "running": True, "pid": os.getpid(), "config": str(self.config_path)}
            elif method == "run":
                action = params.get("action")
                inputs = params.get("input", {})
                actor = params.get("actor")
                cloud = self._get_cloud()
                res = cloud.execute(action=action, inputs=inputs, actor=actor)
                resp = res.to_dict()
            elif method == "actions":
                cloud = self._get_cloud()
                resp = {"ok": True, "actions": [a.to_dict() for a in cloud.actions()]}
            else:
                resp = {"ok": False, "error": f"unknown daemon method {method!r}"}

            conn.sendall(json.dumps(resp).encode("utf-8") + b"\n")
        except Exception as error:
            try:
                conn.sendall(json.dumps({"ok": False, "error": str(error)}).encode("utf-8") + b"\n")
            except OSError:
                pass
        finally:
            conn.close()

    def run_forever(self) -> None:
        self.home.mkdir(parents=True, exist_ok=True)
        if self.sock_path.exists():
            try:
                self.sock_path.unlink()
            except OSError:
                pass

        self._server_sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self._server_sock.bind(str(self.sock_path))
        self._server_sock.listen(128)
        self.pid_path.write_text(str(os.getpid()), encoding="utf-8")
        self._running = True

        def _cleanup(*_):
            self._running = False
            if self.sock_path.exists():
                try: self.sock_path.unlink()
                except OSError: pass
            if self.pid_path.exists():
                try: self.pid_path.unlink()
                except OSError: pass
            sys.exit(0)

        signal.signal(signal.SIGINT, _cleanup)
        signal.signal(signal.SIGTERM, _cleanup)

        while self._running:
            try:
                conn, _ = self._server_sock.accept()
                thread = threading.Thread(target=self.handle_client, args=(conn,), daemon=True)
                thread.start()
            except (OSError, KeyboardInterrupt):
                break
        _cleanup()


def start_daemon_background(config_path: str | Path | None = None) -> dict[str, Any]:
    import subprocess
    if is_daemon_running():
        return {"ok": True, "status": "already_running", "socket": str(daemon_socket_path())}
    
    cmd = [sys.executable, "-c", "from apx.daemon import APXDaemon; APXDaemon().run_forever()"]
    proc = subprocess.Popen(cmd, start_new_session=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    
    for _ in range(20):
        time.sleep(0.05)
        if is_daemon_running():
            return {"ok": True, "status": "started", "pid": proc.pid, "socket": str(daemon_socket_path())}
    
    return {"ok": False, "error": "daemon failed to bind socket"}


def stop_daemon() -> dict[str, Any]:
    pid_file = daemon_pid_path()
    if pid_file.exists():
        try:
            pid = int(pid_file.read_text(encoding="utf-8").strip())
            os.kill(pid, signal.SIGTERM)
            for _ in range(20):
                time.sleep(0.05)
                if not is_daemon_running():
                    return {"ok": True, "status": "stopped"}
        except (ValueError, OSError):
            pass
    sock = daemon_socket_path()
    if sock.exists():
        try: sock.unlink()
        except OSError: pass
    return {"ok": True, "status": "stopped"}
