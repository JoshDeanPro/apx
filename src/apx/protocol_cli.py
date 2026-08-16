# SPDX-License-Identifier: MPL-2.0
"""Protocol-only APX command entrypoint.

The legacy CLI remains an implementation module during the transition, but the
public `apx` command no longer owns LocalCloud runtime/TUI/orchestration UX.
"""
from __future__ import annotations

import sys

from . import cli as legacy_cli

LOCALCLOUD_COMMANDS = {
    "menu",
    "start",
    "localcloud",
    "fleet",
    "hosts",
    "inspect",
    "status",
    "services",
    "service",
    "logs",
    "copy",
    "sync",
    "projects",
    "project",
    "discover-projects",
    "shutdown",
    "hardware",
    "environment",
    "agent",
}

LOCALCLOUD_RENAMES = {
    "menu": "tui",
    "start": "tui",
    "localcloud": "status",
}


def _first_command(argv: list[str]) -> str | None:
    i = 0
    while i < len(argv):
        value = argv[i]
        if value in {"--config", "--actor"}:
            i += 2
            continue
        if value.startswith("--config=") or value.startswith("--actor="):
            i += 1
            continue
        if value.startswith("-"):
            i += 1
            continue
        return value
    return None


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if not args:
        return legacy_cli._main(["--help"])

    command = _first_command(args)
    if command in LOCALCLOUD_COMMANDS:
        replacement = LOCALCLOUD_RENAMES.get(command, command)
        print(
            f"`apx {command}` moved to OpenPower LocalCloud. "
            f"Use `localcloud {replacement}` instead.",
            file=sys.stderr,
        )
        return 2

    return legacy_cli._main(args)


if __name__ == "__main__":
    raise SystemExit(main())
