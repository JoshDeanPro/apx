#!/usr/bin/env python3
"""Adapt an apx config that was copied from another machine to the machine it is
actually on.

Copying apx.toml between hosts looks like it works and does not: the copy still
names some *other* machine as `transport = "local"`, still lists SSH targets
that only resolve from the machine it came from, and still points every
credential at a secret backend that may not exist on this OS (macOS Keychain on
a Linux VPS, for example). `apx --doctor` reports all of that as unreachable
hosts and unavailable credentials -- which is exactly what it was, but the cause
reads as "apx is broken" rather than "this config describes a different
computer."

This rewrites the parts that are machine-specific and leaves everything else --
projects, plugins, actors, policy, comments -- byte-identical:

  * the host marked `transport = "local"` is renamed to --local-name
  * SSH hosts that cannot be resolved from here are dropped (verified, not assumed)
  * `source = "keychain"` credentials become `source = "environment"` when the
    Keychain backend cannot run on this platform, with the reference converted
    to the UPPER_SNAKE env var name the environment backend expects
  * actors pinned to the old local host name follow the rename

Usage:
    python scripts/adapt_config.py --input config.toml --output config.toml \
        --local-name vps [--to-environment-credentials]
"""
from __future__ import annotations

import argparse
import re
import subprocess
import sys
from pathlib import Path


def ssh_resolves(target: str, timeout: int = 6) -> bool:
    """Actually try it. A host is kept only if this machine can reach it."""
    try:
        result = subprocess.run(
            ["ssh", "-o", "BatchMode=yes", "-o", f"ConnectTimeout={timeout}", target, "true"],
            capture_output=True, timeout=timeout + 4,
        )
        return result.returncode == 0
    except (subprocess.TimeoutExpired, OSError):
        return False


def split_blocks(text: str) -> list[str]:
    """Split into TOML blocks, each starting at a [table] / [[array]] header and
    carrying the comments that precede it, so comments stay attached."""
    lines = text.splitlines(keepends=True)
    blocks: list[list[str]] = [[]]
    pending: list[str] = []
    for line in lines:
        if re.match(r"^\s*\[", line):
            blocks.append(pending + [line])
            pending = []
        elif line.strip().startswith("#") or not line.strip():
            pending.append(line)
        else:
            blocks[-1].extend(pending)
            pending = []
            blocks[-1].append(line)
    if pending:
        blocks[-1].extend(pending)
    return ["".join(b) for b in blocks if b]


def block_header(block: str) -> str | None:
    for line in block.splitlines():
        if re.match(r"^\s*\[", line):
            return line.strip()
    return None


def field(block: str, name: str) -> str | None:
    match = re.search(rf'^\s*{name}\s*=\s*"([^"]*)"', block, re.M)
    return match.group(1) if match else None


def main(argv=None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--local-name", required=True, help="what THIS machine should be called")
    parser.add_argument("--to-environment-credentials", action="store_true",
                        help="rewrite keychain credentials to the environment backend (for non-macOS hosts)")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)

    blocks = split_blocks(args.input.read_text(encoding="utf-8"))
    changes: list[str] = []
    old_local: str | None = None
    output: list[str] = []

    for block in blocks:
        header = block_header(block)

        if header == "[[hosts]]":
            name = field(block, "name")
            transport = field(block, "transport")
            if transport == "local":
                old_local = name
                if name != args.local_name:
                    block = re.sub(r'^(\s*name\s*=\s*)"[^"]*"', rf'\1"{args.local_name}"', block, count=1, flags=re.M)
                    changes.append(f"local host renamed: {name} -> {args.local_name}")
            elif transport in {"ssh", "tailscale_ssh"}:
                target = field(block, "target") or ""
                if name == args.local_name:
                    changes.append(f"dropped host {name!r}: it is this machine, reached over ssh to itself")
                    continue
                if not ssh_resolves(target):
                    changes.append(f"dropped host {name!r}: ssh target {target!r} is not reachable from here")
                    continue
                changes.append(f"kept host {name!r}: ssh target {target!r} verified reachable")

        elif header == "[secrets.keychain]" and args.to_environment_credentials:
            changes.append("removed [secrets.keychain]: not available on this platform")
            continue

        elif header and header.startswith("[credentials.") and args.to_environment_credentials:
            if field(block, "source") == "keychain":
                reference = field(block, "reference") or ""
                env_name = re.sub(r"[^A-Za-z0-9]+", "_", reference).upper().strip("_")
                block = re.sub(r'^(\s*source\s*=\s*)"keychain"', r'\1"environment"', block, count=1, flags=re.M)
                block = re.sub(r'^(\s*reference\s*=\s*)"[^"]*"', rf'\1"{env_name}"', block, count=1, flags=re.M)
                changes.append(f"{header[1:-1]}: keychain -> environment (${env_name})")

        elif header == "[[actors]]" and old_local:
            if field(block, "host") == old_local:
                block = re.sub(rf'^(\s*host\s*=\s*)"{re.escape(old_local)}"', rf'\1"{args.local_name}"', block, count=1, flags=re.M)
                block = re.sub(rf'^(\s*id\s*=\s*"[^"]*):{re.escape(old_local)}"', rf'\1:{args.local_name}"', block, count=1, flags=re.M)
                changes.append(f"actor repinned from host {old_local} to {args.local_name}")

        output.append(block)

    result = "".join(output)
    for change in changes:
        print(f"  {change}", file=sys.stderr)
    if args.dry_run:
        print(result)
    else:
        args.output.write_text(result, encoding="utf-8")
        print(f"wrote {args.output} ({len(changes)} changes)", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
