# SPDX-License-Identifier: MIT
"""Test interactive TUI navigation in a pseudo-terminal (PTY) and CLI formatting."""
from __future__ import annotations
import termios
import subprocess
import struct
import fcntl

import json
import os
import pty
import re
import select
import sys
import time
import pytest

from apx.cli import _main


ANSI_ESCAPE = re.compile(r'\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])')


def clean_ansi(text: str) -> str:
    return ANSI_ESCAPE.sub('', text)


def test_cli_help_and_version(capsys):
    with pytest.raises(SystemExit) as exc:
        _main(["--version"])
    assert exc.value.code == 0

    code = _main(["version"])
    assert code == 0
    captured = capsys.readouterr()
    assert "APX" in captured.out

    code = _main(["version", "--json"])
    assert code == 0
    captured = capsys.readouterr()
    data = json.loads(captured.out)
    assert "version" in data


def test_cli_actions_formatting_and_json(capsys):
    code = _main(["actions"])
    assert code == 0
    captured = capsys.readouterr()
    assert "Actions Catalog" in captured.out
    assert "host.inspect" in captured.out

    code = _main(["actions", "--json"])
    assert code == 0
    captured = capsys.readouterr()
    data = json.loads(captured.out)
    assert "actions" in data
    assert any(a["id"] == "host.inspect" for a in data["actions"])


def test_cli_whoami_formatting_and_json(capsys):
    code = _main(["whoami"])
    assert code == 0
    captured = capsys.readouterr()
    assert "Actor & Identity" in captured.out

    code = _main(["whoami", "--json"])
    assert code == 0
    captured = capsys.readouterr()
    data = json.loads(captured.out)
    assert "actor" in data or "id" in data or "ok" in data


def test_cli_conformance_formatting_and_json(capsys):
    code = _main(["conformance"])
    assert code == 0
    captured = capsys.readouterr()
    assert "CONFORMANCE PASS" in captured.out

    code = _main(["conformance", "--json"])
    assert code == 0
    captured = capsys.readouterr()
    data = json.loads(captured.out)
    assert data.get("ok") is True
    assert data.get("conformance") == "pass"


def test_cli_prompt_and_shared_settings_commands(capsys):
    # 1. Prompts list
    code = _main(["prompts", "--json"])
    assert code == 0
    captured = capsys.readouterr()
    data = json.loads(captured.out)
    prompts = data.get("result", {}).get("prompts") or data.get("prompts") or []
    assert len(prompts) > 0

    # 2. Shared settings list
    code = _main(["shared-settings", "--json"])
    assert code == 0
    captured = capsys.readouterr()
    data = json.loads(captured.out)
    settings = data.get("result", {}).get("settings") or data.get("settings") or []
    assert len(settings) > 0


class PTYSession:
    def __init__(self):
        self.master, self.slave = pty.openpty()
        self.pid = os.fork()
        if self.pid == 0:
            os.close(self.master)
            os.setsid()
            os.dup2(self.slave, 0)
            os.dup2(self.slave, 1)
            os.dup2(self.slave, 2)
            os.close(self.slave)
            os.environ["TERM"] = "xterm-256color"
            os.environ["PYTHONPATH"] = "src"
            os.execl(sys.executable, sys.executable, "-m", "apx.cli")
            sys.exit(1)
        os.close(self.slave)
        self.buffer = bytearray()

    def write(self, data: bytes):
        os.write(self.master, data)

    def wait_for(self, expected: str | list[str], timeout: float = 3.0) -> str:
        expected_list = [expected] if isinstance(expected, str) else expected
        end = time.time() + timeout
        while time.time() < end:
            r, _, _ = select.select([self.master], [], [], 0.05)
            if r:
                try:
                    chunk = os.read(self.master, 4096)
                    if not chunk:
                        break
                    self.buffer.extend(chunk)
                    cleaned = clean_ansi(self.buffer.decode("utf-8", errors="ignore"))
                    if all(exp in cleaned for exp in expected_list):
                        return cleaned
                except OSError:
                    break
        return clean_ansi(self.buffer.decode("utf-8", errors="ignore"))

    def close(self):
        try:
            self.write(b"\x03")
        except OSError:
            pass
        os.close(self.master)
        try:
            os.kill(self.pid, 9)
            os.waitpid(self.pid, 0)
        except OSError:
            pass


class InkSession:
    def __init__(self, args=None):
        self.master, slave = pty.openpty()

        fcntl.ioctl(
            slave,
            termios.TIOCSWINSZ,
            struct.pack(
                "HHHH",
                50,
                140,
                0,
                0,
            ),
        )

        env = os.environ.copy()
        env["TERM"] = "xterm-256color"
        env["NODE_ENV"] = "production"
        env["DEV"] = "false"

        command = [
            sys.executable,
            "-c",
            "from apx.entry import main; raise SystemExit(main())",
            *(args or []),
        ]

        self.process = subprocess.Popen(
            command,
            stdin=slave,
            stdout=slave,
            stderr=slave,
            env=env,
            close_fds=True,
        )

        os.close(slave)

        os.set_blocking(
            self.master,
            False,
        )

        self.output = bytearray()

    def clear(self):
        self.output = bytearray()

        while True:
            try:
                chunk = os.read(
                    self.master,
                    65536,
                )

                if not chunk:
                    break

            except BlockingIOError:
                break

            except OSError:
                break

    def write(self, data):
        self.clear()

        os.write(
            self.master,
            data,
        )

    def wait_for(self, markers, timeout=4.0):
        deadline = (
            time.time()
            + timeout
        )

        while (
            time.time()
            < deadline
        ):
            try:
                chunk = os.read(
                    self.master,
                    65536,
                )

                if chunk:
                    self.output.extend(
                        chunk
                    )

            except BlockingIOError:
                pass

            except OSError:
                break

            text = self.output.decode(
                "utf-8",
                errors="ignore",
            )

            if all(
                marker in text
                for marker
                in markers
            ):
                return text

            if (
                self.process.poll()
                is not None
            ):
                break

            time.sleep(
                0.03
            )

        text = self.output.decode(
            "utf-8",
            errors="ignore",
        )

        raise AssertionError(
            "Missing screen content: "
            + ", ".join(markers)
            + "\nOutput:\n"
            + text
        )

    def close(self):
        for _ in range(8):
            if (
                self.process.poll()
                is not None
            ):
                break

            try:
                os.write(
                    self.master,
                    b"\x1b",
                )
            except OSError:
                break

            time.sleep(
                0.05
            )

        if (
            self.process.poll()
            is None
        ):
            self.process.terminate()

            try:
                self.process.wait(
                    timeout=2
                )

            except subprocess.TimeoutExpired:
                self.process.kill()
                self.process.wait(
                    timeout=2
                )

        try:
            os.close(
                self.master
            )

        except OSError:
            pass


def test_tui_root_menu_and_devices_navigation_in_pty():
    session = InkSession()

    try:
        session.wait_for(
            [
                "Devices",
                "Agents",
                "Prompts",
                "Services",
                "Plugins",
                "OpenPower Settings",
            ]
        )

        session.write(
            b"\r"
        )

        text = session.wait_for(
            [
                "Devices",
                "Search",
            ]
        )

        assert "Search" in text

    finally:
        session.close()

def test_tui_services_porkbun_domains_flow_in_pty():
    session = InkSession()

    try:
        session.wait_for(
            [
                "Devices",
                "Services",
            ]
        )

        # 1. Press 4 for Services
        session.write(b"4")
        session.wait_for(
            [
                "Services",
                "Porkbun",
            ]
        )

        # 2. Porkbun is index 1 on the Services screen.
        os.write(session.master, b"j")
        time.sleep(0.15)
        session.clear()
        
        # 3. Press Enter to select Porkbun
        os.write(session.master, b"\r")
        session.wait_for(
            [
                "Porkbun",
                "Domains",
                "Credentials",
            ]
        )

        # 4. Domains is index 0. Select it.
        session.write(b"\r")
        
        # 5. Wait for Error View OR Success Domains View
        deadline = time.time() + 4.0
        success = False
        text = ""
        while time.time() < deadline:
            try:
                chunk = os.read(session.master, 65536)
                if chunk:
                    session.output.extend(chunk)
            except BlockingIOError:
                pass
            except OSError:
                break
                
            text = session.output.decode("utf-8", errors="ignore")
            
            # Error Case (missing credentials or network)
            if "Something went wrong" in text and "Porkbun" in text:
                success = True
                break
                
            # Success Case (has credentials and network)
            if "esc back" in text and "Search" in text and "Domains" in text:
                success = True
                break
                    
            if session.process.poll() is not None:
                break
            time.sleep(0.03)
            
        if not success:
            raise AssertionError("Missing expected Domains state. Output:\n" + text)

        # 6. Press Esc to go back to Porkbun Service Screen
        session.write(b"\x1b")
        session.wait_for(
            [
                "Porkbun",
                "Domains",
                "Credentials",
            ]
        )

        # 7. Press Esc to go back to Services Screen
        session.write(b"\x1b")
        session.wait_for(
            [
                "Services",
                "Porkbun",
            ]
        )

    finally:
        session.close()

def test_tui_openpower_settings_and_servers_in_pty():
    session = InkSession()

    try:
        session.wait_for(
            [
                "OpenPower Settings",
            ]
        )

        session.write(
            b"6"
        )

        text = session.wait_for(
            [
                "Link Account",
                "Servers",
                "Documentation",
            ]
        )

        assert "Link Account" in text
        assert "Servers" in text
        assert "Documentation" in text

    finally:
        session.close()

def test_tui_search_filter_and_help_modal_in_pty():
    session = InkSession()

    try:
        session.wait_for(
            [
                "Devices",
                "Plugins",
            ]
        )

        session.write(
            b"?"
        )

        text = session.wait_for(
            [
                "Navigation Controls",
            ]
        )

        assert "Navigation Controls" in text

        session.write(
            b"\x1b"
        )

        session.wait_for(
            [
                "Devices",
                "Plugins",
            ]
        )

        session.write(
            b"5"
        )

        text = session.wait_for(
            [
                "Plugins",
                "Search",
            ]
        )

        assert "Search" in text

    finally:
        session.close()
