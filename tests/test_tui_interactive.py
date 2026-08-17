# SPDX-License-Identifier: MPL-2.0
"""Test interactive TUI navigation in a pseudo-terminal (PTY) and CLI formatting."""
from __future__ import annotations

import json
import os
import pty
import select
import sys
import time
import pytest

from apx.cli import _main


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
    # Human formatted table
    code = _main(["actions"])
    assert code == 0
    captured = capsys.readouterr()
    assert "Actions Catalog" in captured.out
    assert "host.inspect" in captured.out

    # Machine readable JSON
    code = _main(["actions", "--json"])
    assert code == 0
    captured = capsys.readouterr()
    data = json.loads(captured.out)
    assert "actions" in data
    assert any(a["id"] == "host.inspect" for a in data["actions"])


def test_cli_whoami_formatting_and_json(capsys):
    # Human formatted card
    code = _main(["whoami"])
    assert code == 0
    captured = capsys.readouterr()
    assert "Actor & Identity" in captured.out

    # JSON
    code = _main(["whoami", "--json"])
    assert code == 0
    captured = capsys.readouterr()
    data = json.loads(captured.out)
    assert "actor" in data or "id" in data or "ok" in data


def test_cli_conformance_formatting_and_json(capsys):
    # Human formatted badge
    code = _main(["conformance"])
    assert code == 0
    captured = capsys.readouterr()
    assert "CONFORMANCE PASS" in captured.out

    # JSON
    code = _main(["conformance", "--json"])
    assert code == 0
    captured = capsys.readouterr()
    data = json.loads(captured.out)
    assert data.get("ok") is True
    assert data.get("conformance") == "pass"


def test_cli_action_inspect_and_run(capsys):
    code = _main(["action", "inspect", "host.inspect"])
    assert code == 0
    captured = capsys.readouterr()
    assert "Action: host.inspect" in captured.out
    assert "READ" in captured.out


def test_tui_launches_and_navigates_in_pty():
    master, slave = pty.openpty()

    pid = os.fork()
    if pid == 0:
        os.close(master)
        os.setsid()
        os.dup2(slave, 0)
        os.dup2(slave, 1)
        os.dup2(slave, 2)
        os.close(slave)

        os.environ["TERM"] = "xterm-256color"
        os.environ["PYTHONPATH"] = "src"
        os.execl("/Users/ethan/.local/share/apx/runtime/bin/python3", "python3", "-m", "apx.cli")
        sys.exit(1)

    os.close(slave)
    output = bytearray()

    def read_output(timeout=0.5):
        end = time.time() + timeout
        accum = bytearray()
        while time.time() < end:
            r, _, _ = select.select([master], [], [], 0.1)
            if r:
                try:
                    chunk = os.read(master, 4096)
                    if not chunk:
                        break
                    output.extend(chunk)
                    accum.extend(chunk)
                except OSError:
                    break
        return accum

    try:
        # Wait for TUI to initialize and render header
        read_output(timeout=1.5)
        text = output.decode("utf-8", errors="ignore")
        assert "APX PROTOCOL" in text or "Overview" in text

        # Send Down Arrow (\x1b[B) to move selection
        os.write(master, b"\x1b[B")
        read_output(timeout=0.5)

        # Send Tab to switch to Actions tab
        os.write(master, b"\t")
        read_output(timeout=0.5)
        text = output.decode("utf-8", errors="ignore")
        assert "Actions" in text

        # Send 'q' to quit cleanly
        os.write(master, b"q")
        read_output(timeout=1.0)

        _, status = os.waitpid(pid, 0)
        exit_code = os.waitstatus_to_exitcode(status)
        assert exit_code == 0
    finally:
        os.close(master)
        try:
            os.kill(pid, 9)
        except OSError:
            pass


def test_tui_number_keys_and_search_filter_in_pty():
    master, slave = pty.openpty()

    pid = os.fork()
    if pid == 0:
        os.close(master)
        os.setsid()
        os.dup2(slave, 0)
        os.dup2(slave, 1)
        os.dup2(slave, 2)
        os.close(slave)

        os.environ["TERM"] = "xterm-256color"
        os.environ["PYTHONPATH"] = "src"
        os.execl("/Users/ethan/.local/share/apx/runtime/bin/python3", "python3", "-m", "apx.cli")
        sys.exit(1)

    os.close(slave)
    output = bytearray()

    def read_output(timeout=0.5):
        end = time.time() + timeout
        accum = bytearray()
        while time.time() < end:
            r, _, _ = select.select([master], [], [], 0.1)
            if r:
                try:
                    chunk = os.read(master, 4096)
                    if not chunk:
                        break
                    output.extend(chunk)
                    accum.extend(chunk)
                except OSError:
                    break
        return accum

    try:
        read_output(timeout=1.5)

        # Press '2' for Actions tab
        os.write(master, b"2")
        read_output(timeout=0.5)
        text = output.decode("utf-8", errors="ignore")
        assert "Actions" in text

        # Press '/' to activate filter and type 'drift'
        os.write(master, b"/")
        read_output(timeout=0.2)
        os.write(master, b"drift")
        read_output(timeout=0.4)
        text = output.decode("utf-8", errors="ignore")
        assert "drift" in text

        # Press Escape to clear search filter
        os.write(master, b"\x1b")
        read_output(timeout=0.4)

        # Press 'q' to quit cleanly
        os.write(master, b"q")
        read_output(timeout=1.0)

        _, status = os.waitpid(pid, 0)
        exit_code = os.waitstatus_to_exitcode(status)
        assert exit_code == 0
    finally:
        os.close(master)
        try:
            os.kill(pid, 9)
        except OSError:
            pass
