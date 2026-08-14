#!/usr/bin/env python3
"""Build the verified apx wheel and release manifest served by openpower.dev.

Replaces openpower/cli_installer/build_release.py, which built two wheels (apx
plus a separate `op` CLI). `op` has been retired -- apx is the whole CLI now --
so this builds one wheel and writes a schema-2 manifest with no openpower_cli
artifact. The installer (website/public/downloads/install.sh and install.ps1)
reads that manifest and verifies these checksums before installing anything.

Usage:
    python scripts/build_release.py --output ../openpower/website/public/downloads
"""
from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent


def _version() -> str:
    """Read the version from pyproject rather than hardcoding it, so a release
    built from a bumped checkout cannot silently claim the previous version."""
    for line in (REPO / "pyproject.toml").read_text(encoding="utf-8").splitlines():
        if line.startswith("version"):
            return line.split("=", 1)[1].strip().strip('"')
    raise SystemExit("could not determine apx version from pyproject.toml")


def main(argv=None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    version = _version()

    subprocess.run([sys.executable, "-m", "pip", "wheel", "--no-deps", "--wheel-dir", str(output), str(REPO)], check=True)
    wheel = next(output.glob(f"apx-{version}-*.whl"))

    lock = REPO / "scripts" / "foundation.lock"
    target_lock = output / lock.name
    target_lock.write_bytes(lock.read_bytes())

    def item(path: Path) -> dict:
        return {
            "filename": path.name,
            "url": f"https://openpower.dev/downloads/{path.name}",
            "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        }

    manifest = {"schema": 2, "apx_version": version, "artifacts": {"apx": item(wheel), "constraints": item(target_lock)}}
    (output / "foundation-manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    print(json.dumps(manifest, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
