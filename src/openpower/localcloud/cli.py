# SPDX-License-Identifier: MPL-2.0
from __future__ import annotations

import argparse
import json
import sys

from . import LocalCloud, localcloud_get, localcloud_set, localcloud_status, localcloud_sync_peer

# Commands still temporarily implemented by the legacy APX operational CLI.
# LocalCloud-native commands (status/get/set/sync/run/tui) must NOT appear here,
# otherwise they are intercepted before LocalCloud's own parser sees them.
LEGACY_OPERATIONAL_COMMANDS = {
    "fleet",
    "hosts",
    "inspect",
    "services",
    "service",
    "logs",
    "copy",
    "projects",
    "project",
    "discover-projects",
    "shutdown",
    "hardware",
    "environment",
    "agent",
}


def _output(value: object) -> None:
    print(json.dumps(value, indent=2, ensure_ascii=False))


def _legacy_passthrough(argv: list[str]) -> int:
    """Temporary compatibility bridge while operational commands migrate modules."""
    from apx import cli as legacy_cli
    return legacy_cli._main(argv)


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)

    if args and args[0] in LEGACY_OPERATIONAL_COMMANDS:
        return _legacy_passthrough(args)

    parser = argparse.ArgumentParser(
        prog="localcloud",
        description="OpenPower LocalCloud — local runtime, orchestration, and host-sovereign state built on APX.",
    )
    parser.add_argument("--config", help="APX/LocalCloud TOML configuration path")
    sub = parser.add_subparsers(dest="command")

    sub.add_parser("status", help="show LocalCloud vault/runtime status")
    getp = sub.add_parser("get", help="read one LocalCloud vault value")
    getp.add_argument("key")
    setp = sub.add_parser("set", help="store one LocalCloud vault value")
    setp.add_argument("key")
    setp.add_argument("value")
    syncp = sub.add_parser("sync", help="register/update a LocalCloud mesh peer")
    syncp.add_argument("peer_id")
    syncp.add_argument("host")
    syncp.add_argument("token")
    runp = sub.add_parser("run", help="run an APX action through the LocalCloud runtime")
    runp.add_argument("action")
    runp.add_argument("--actor")
    runp.add_argument("--input", default="{}", help="JSON object of action inputs")
    sub.add_parser("tui", help="launch the OpenPower interactive environment")

    ns, extra = parser.parse_known_args(args)
    if ns.command is None:
        parser.print_help()
        return 0
    if extra:
        parser.error("unrecognized arguments: " + " ".join(extra))

    if ns.command == "status":
        _output(localcloud_status())
        return 0
    if ns.command == "get":
        value = localcloud_get(ns.key)
        _output({"ok": value is not None, "key": ns.key, "value": value})
        return 0 if value is not None else 1
    if ns.command == "set":
        _output(localcloud_set(ns.key, ns.value))
        return 0
    if ns.command == "sync":
        _output(localcloud_sync_peer(ns.peer_id, ns.host, ns.token))
        return 0
    if ns.command == "run":
        try:
            inputs = json.loads(ns.input)
        except json.JSONDecodeError as exc:
            parser.error(f"--input must be JSON: {exc}")
        result = LocalCloud(ns.config).run(ns.action, actor=ns.actor, **inputs)
        _output(result.to_dict() if hasattr(result, "to_dict") else result)
        return 0 if getattr(result, "ok", True) else 1
    if ns.command == "tui":
        # The interactive UI is now LocalCloud-owned. Keep using the mature
        # implementation while it is physically migrated out of apx.tui.
        from apx.tui import main as tui_main
        return tui_main()

    return 2


if __name__ == "__main__":
    raise SystemExit(main())
