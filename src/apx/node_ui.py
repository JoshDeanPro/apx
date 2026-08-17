from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path


def ui_directory() -> Path:
    target = (
        Path(__file__).resolve().parent
        / "_ui"
    )

    if not (
        target
        / "index.mjs"
    ).exists():
        raise FileNotFoundError(
            "The APX terminal interface is missing."
        )

    return target


def ensure_runtime(
    directory: Path,
) -> None:
    ink = (
        directory
        / "node_modules"
        / "ink"
        / "package.json"
    )

    react = (
        directory
        / "node_modules"
        / "react"
        / "package.json"
    )

    if (
        ink.exists()
        and react.exists()
    ):
        return

    npm = shutil.which(
        "npm"
    )

    if not npm:
        raise RuntimeError(
            "APX needs npm to prepare the terminal interface."
        )

    result = subprocess.run(
        [
            npm,
            "ci",
            "--omit=dev",
            "--no-audit",
            "--no-fund",
        ],
        cwd=str(
            directory
        ),
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
        text=True,
    )

    if result.returncode != 0:
        raise RuntimeError(
            result.stderr.strip()
            or
            "The APX terminal interface could not be prepared."
        )


def run_ui(
    argv: list[str] | None = None,
) -> int:
    node = shutil.which(
        "node"
    )

    if not node:
        sys.stderr.write(
            "APX needs Node.js 22 or newer to open the interactive interface.\n"
        )
        return 7

    try:
        major = int(
            subprocess.check_output(
                [
                    node,
                    "-p",
                    "Number(process.versions.node.split('.')[0])",
                ],
                text=True,
            ).strip()
        )

    except Exception:
        major = 0

    if major < 22:
        sys.stderr.write(
            "APX needs Node.js 22 or newer to open the interactive interface.\n"
        )
        return 7

    try:
        directory = ui_directory()
        ensure_runtime(
            directory
        )

    except (
        FileNotFoundError,
        RuntimeError,
    ) as exc:
        sys.stderr.write(
            f"{exc}\n"
        )
        return 7

    env = os.environ.copy()

    env[
        "APX_PYTHON"
    ] = sys.executable

    env[
        "NODE_ENV"
    ] = "production"

    env[
        "DEV"
    ] = "false"

    env.pop(
        "APX_UI_HOME",
        None,
    )

    try:
        return subprocess.call(
            [
                node,
                str(
                    directory
                    / "index.mjs"
                ),
                *(argv or []),
            ],
            cwd=str(
                directory
            ),
            env=env,
        )

    except KeyboardInterrupt:
        return 130
