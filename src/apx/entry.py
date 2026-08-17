from __future__ import annotations

import sys

from .cli import main as cli_main
from .node_ui import run_ui


def main() -> int:
    args = list(
        sys.argv[1:]
    )

    interactive = (
        sys.stdin.isatty()
        and sys.stdout.isatty()
    )

    if interactive and not args:
        return run_ui([])

    if (
        interactive
        and args == ["update"]
    ):
        return run_ui(
            ["update"]
        )

    result = cli_main()

    return (
        0
        if result is None
        else int(result)
    )
