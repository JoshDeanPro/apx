from __future__ import annotations

import getpass
import json
import os
import re
import shlex
import shutil
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from prompt_toolkit import Application
from prompt_toolkit.formatted_text import FormattedText
from prompt_toolkit.key_binding import KeyBindings
from prompt_toolkit.layout import Layout
from prompt_toolkit.layout.controls import (
    FormattedTextControl,
)
from prompt_toolkit.layout.containers import (
    HSplit,
    Window,
)
from prompt_toolkit.styles import Style

from rich.console import Console
from rich.table import Table

from .network_state import (
    NETWORK_FILE,
    cached as network_cached,
    refresh as network_refresh,
    run_remote,
)
from .providers_builtin import (
    porkbun_domains,
    purelymail_credit,
    purelymail_create_user,
    purelymail_delete_user,
    purelymail_domains,
    purelymail_users,
)

HOME = Path.home()

CONFIG = HOME / ".config" / "apx"
STATE = HOME / ".local" / "state" / "apx"
SHARE = HOME / ".local" / "share" / "apx"

REAL = (
    SHARE
    / "runtime"
    / "bin"
    / "apx"
)

META = CONFIG / "tui.json"
CHANNELS = CONFIG / "channels.json"
LINKS = CONFIG / "links.json"
STANDING = CONFIG / "standing-agents.json"

VOICE_CONFIG = CONFIG / "voice.json"
VOICE_PID = STATE / "voice" / "daemon.pid"

console = Console()


@dataclass
class Item:
    key: str
    label: str
    detail: str = ""
    kind: str = ""
    data: dict[str, Any] = field(
        default_factory=dict
    )


@dataclass
class Screen:
    key: str
    title: str
    context: dict[str, Any] = field(
        default_factory=dict
    )
    index: int = 0
    multi: set[str] = field(
        default_factory=set
    )


def load_json(
    path: Path,
    default: Any,
) -> Any:
    try:
        return json.loads(
            path.read_text()
        )
    except Exception:
        return default


def save_json(
    path: Path,
    value: Any,
) -> None:
    path.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    tmp = path.with_suffix(
        path.suffix + ".tmp"
    )

    tmp.write_text(
        json.dumps(
            value,
            indent=2,
        )
        + "\n"
    )

    os.chmod(tmp, 0o600)
    tmp.replace(path)


def pause() -> None:
    try:
        input(
            "\nPress Return to return to APX..."
        )
    except (
        EOFError,
        KeyboardInterrupt,
    ):
        pass


def _real_cmd() -> list[str]:
    if REAL.exists():
        return [str(REAL)]
    found = shutil.which("apx")
    if found:
        return [found]
    return [sys.executable, "-m", "apx.cli"]


def native(
    *args: str,
) -> int:
    try:
        return subprocess.call(
            [
                *_real_cmd(),
                *args,
            ]
        )
    except (
        EOFError,
        KeyboardInterrupt,
    ):
        return 130


def native_capture(
    *args: str,
) -> str:
    p = subprocess.run(
        [
            *_real_cmd(),
            *args,
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        check=False,
    )

    return p.stdout.strip()



def voice_state() -> tuple[str, str]:
    cfg = load_json(
        VOICE_CONFIG,
        {},
    )

    if not isinstance(cfg, dict):
        cfg = {}

    enabled = bool(
        cfg.get(
            "enabled",
            False,
        )
    )

    mode = str(
        cfg.get(
            "mode",
            "off",
        )
    ).replace(
        "_",
        " ",
    )

    running = False

    try:
        pid = int(
            VOICE_PID.read_text().strip()
        )
        os.kill(
            pid,
            0,
        )
        running = True
    except Exception:
        pass

    if not enabled:
        return (
            "OFF",
            mode,
        )

    return (
        (
            "LISTENING"
            if running
            else "READY"
        ),
        mode,
    )


def channels_data() -> dict[str, Any]:
    value = load_json(
        CHANNELS,
        {},
    )

    if not isinstance(value, dict):
        value = {}

    defaults = {
        "terminal": {
            "type": "terminal",
            "enabled": True,
            "purposes": [
                "approvals",
                "agent-replies",
            ],
        },
        "openpower": {
            "type": "openpower",
            "enabled": True,
            "purposes": [
                "status",
            ],
        },
        "email": {
            "type": "email",
            "enabled": False,
            "purposes": [],
        },
        "discord": {
            "type": "discord",
            "enabled": False,
            "purposes": [],
        },
    }

    for key, default in defaults.items():
        value.setdefault(
            key,
            default,
        )

    return value


def save_channels(
    value: dict[str, Any],
) -> None:
    save_json(
        CHANNELS,
        value,
    )


def links_data() -> dict[str, Any]:
    value = load_json(
        LINKS,
        {},
    )

    if not isinstance(value, dict):
        value = {}

    value.setdefault(
        "credentials",
        {},
    )
    value.setdefault(
        "agents",
        {},
    )

    return value


def save_links(
    value: dict[str, Any],
) -> None:
    save_json(
        LINKS,
        value,
    )


def standing_data() -> dict[str, Any]:
    value = load_json(
        STANDING,
        {},
    )

    if not isinstance(value, dict):
        return {}

    return value


def save_standing(
    value: dict[str, Any],
) -> None:
    save_json(
        STANDING,
        value,
    )


def projects() -> list[Path]:
    result: list[Path] = []

    direct = [
        HOME / "apx",
        HOME / "openpower",
        HOME / "Projects",
    ]

    for path in direct:
        if path.exists():
            result.append(path)

    root = HOME / "Projects"

    if root.is_dir():
        try:
            for child in sorted(
                root.iterdir()
            ):
                if child.is_dir():
                    result.append(child)
        except Exception:
            pass

    seen = set()
    final = []

    for path in result:
        key = str(
            path.resolve()
        )

        if key in seen:
            continue

        seen.add(key)
        final.append(path)

    return final


def credential_ids() -> list[str]:
    result = {
        "porkbun_api_key",
        "porkbun_secret_key",
        "purelymail_credential",
        "cloudflare_credential",
        "discord_bot_credential",
        "openai_credential",
        "paddle_credential",
    }

    config_file = (
        CONFIG / "config.toml"
    )

    if config_file.exists():
        try:
            text = config_file.read_text()

            for match in re.findall(
                r"\b"
                r"([A-Za-z0-9_.-]+"
                r"(?:credential|api_key|secret_key|token))"
                r"\b",
                text,
                flags=re.I,
            ):
                result.add(
                    match
                )
        except Exception:
            pass

    links = links_data()

    result.update(
        links.get(
            "credentials",
            {},
        ).keys()
    )

    return sorted(result)


def agent_records() -> list[dict[str, Any]]:
    network = network_cached()

    result = []

    for machine, info in network.get(
        "machines",
        {},
    ).items():
        for agent, details in info.get(
            "agents",
            {},
        ).items():
            result.append(
                {
                    "machine": machine,
                    "machine_name": info.get(
                        "name",
                        machine,
                    ),
                    "online": info.get(
                        "online",
                        False,
                    ),
                    "agent": agent,
                    **details,
                }
            )

    return result


def current_screen_items(
    screen: Screen,
) -> list[Item]:
    key = screen.key

    if key == "main":
        voice_status, voice_mode = (
            voice_state()
        )

        network = network_cached()

        machine_count = len(
            network.get(
                "machines",
                {},
            )
        )

        online_count = sum(
            1
            for value in network.get(
                "machines",
                {},
            ).values()
            if value.get("online")
        )

        return [
            Item(
                "computers",
                "Computers",
                f"{online_count}/{machine_count} online",
            ),
            Item(
                "agents",
                "AI Agents",
                ", Codex, standing sessions",
            ),
            Item(
                "credentials",
                "Passwords & API Keys",
                "Tokens, links, permissions",
            ),
            Item(
                "plugins",
                "Plugins & Services",
                "Porkbun, Purelymail, APIs",
            ),
            Item(
                "channels",
                "Channels",
                "Multi-channel routing",
            ),
            Item(
                "projects",
                "Projects",
                "Link projects to agents and credentials",
            ),
            Item(
                "voice",
                "Voice Agent",
                f"{voice_status} • {voice_mode}",
            ),
            Item(
                "network",
                "Network",
                "Direct APX computer routes",
            ),
            Item(
                "settings",
                "Settings",
                "Doctor, updates, auto-check, environment",
            ),
        ]

    if key == "computers":
        network = network_cached()

        items = []

        for machine, info in network.get(
            "machines",
            {},
        ).items():
            online = bool(
                info.get(
                    "online",
                    False,
                )
            )

            apx = info.get(
                "apx",
                {},
            )

            detail = (
                (
                    "ONLINE"
                    if online
                    else "OFFLINE"
                )
                + " • "
                + str(
                    info.get(
                        "role",
                        "",
                    )
                )
            )

            if online:
                latency = info.get(
                    "latency_ms"
                )

                if latency is not None:
                    detail += (
                        f" • {latency} ms"
                    )

                detail += (
                    " • APX "
                    + (
                        "ready"
                        if apx.get(
                            "installed"
                        )
                        else "missing"
                    )
                )

            items.append(
                Item(
                    machine,
                    info.get(
                        "name",
                        machine,
                    ),
                    detail,
                    "computer",
                    {
                        "machine": machine,
                    },
                )
            )

        return items

    if key == "computer":
        machine = screen.context[
            "machine"
        ]

        network = network_cached()

        info = network.get(
            "machines",
            {},
        ).get(
            machine,
            {},
        )

        return [
            Item(
                "agents",
                "AI Agents",
                "Installed / ready / running",
            ),
            Item(
                "shell",
                "Open Shell",
                str(
                    info.get(
                        "target"
                    )
                    or "local"
                ),
            ),
            Item(
                "doctor",
                "Run APX Doctor",
            ),
            Item(
                "version",
                "APX Version",
            ),
            Item(
                "refresh",
                "Refresh This Computer",
            ),
        ]

    if key == "agents":
        result = []

        standing = standing_data()

        for record in agent_records():
            machine = record["machine"]
            agent = record["agent"]

            identifier = (
                f"{machine}:{agent}"
            )

            installed = record.get(
                "installed",
                False,
            )

            online = record.get(
                "online",
                False,
            )

            processes = int(
                record.get(
                    "processes",
                    0,
                )
                or 0
            )

            requested = bool(
                standing.get(
                    identifier,
                    {},
                ).get(
                    "standing",
                    False,
                )
            )

            if not online:
                state = "OFFLINE"
            elif not installed:
                state = "NOT INSTALLED"
            elif processes:
                state = (
                    f"RUNNING ({processes})"
                )
            else:
                state = "READY"

            if requested:
                state += " • STANDING"

            result.append(
                Item(
                    identifier,
                    (
                        f"{agent.title()}"
                        f"  —  "
                        f"{record['machine_name']}"
                    ),
                    state,
                    "agent",
                    {
                        "machine": machine,
                        "agent": agent,
                    },
                )
            )

        return result

    if key == "agent":
        machine = screen.context[
            "machine"
        ]
        agent = screen.context[
            "agent"
        ]

        identifier = (
            f"{machine}:{agent}"
        )

        standing = bool(
            standing_data()
            .get(
                identifier,
                {},
            )
            .get(
                "standing",
                False,
            )
        )

        return [
            Item(
                "start",
                "Start Interactive Session",
            ),
            Item(
                "standing",
                (
                    "Disable Standing Agent"
                    if standing
                    else "Make Standing Agent"
                ),
                (
                    "Standing = available profile, "
                    "separate from active model usage"
                ),
            ),
            Item(
                "attach",
                "Attach Standing Session",
                "Uses tmux when a standing process exists",
            ),
            Item(
                "stop",
                "Stop Standing Session",
            ),
            Item(
                "project",
                "Link Project",
            ),
            Item(
                "channels",
                "Link Channels",
                "SPACE selects multiple",
            ),
            Item(
                "refresh",
                "Refresh Agent State",
            ),
        ]

    if key == "credentials":
        links = links_data().get(
            "credentials",
            {},
        )

        result = [
            Item(
                "__add__",
                "+ Add Another Credential",
                "Create a new APX secret reference",
            )
        ]

        for identifier in credential_ids():
            linked = links.get(
                identifier,
                {},
            )

            counts = []

            for label in (
                "agents",
                "projects",
                "channels",
            ):
                count = len(
                    linked.get(
                        label,
                        [],
                    )
                )

                if count:
                    counts.append(
                        f"{count} {label}"
                    )

            detail = (
                " • ".join(counts)
                if counts
                else "No links"
            )

            result.append(
                Item(
                    identifier,
                    identifier,
                    detail,
                    "credential",
                    {
                        "credential": (
                            identifier
                        )
                    },
                )
            )

        return result

    if key == "credential":
        identifier = screen.context[
            "credential"
        ]

        return [
            Item(
                "set",
                "Set / Replace Token",
                "Uses APX secure secret backend",
            ),
            Item(
                "reveal",
                "Reveal Token",
                "Explicit secret reveal",
            ),
            Item(
                "remove",
                "Remove / Revoke Token",
                "Revokes APX credential access",
            ),
            Item(
                "agents",
                "Link AI Agents",
                "SPACE selects multiple",
            ),
            Item(
                "projects",
                "Link Projects",
                "SPACE selects multiple",
            ),
            Item(
                "channels",
                "Link Channels",
                "SPACE selects multiple",
            ),
        ]

    if key == "plugins":
        return [
            Item(
                "porkbun",
                "Porkbun",
                "Domains + API access",
                "plugin",
                {
                    "plugin": "porkbun"
                },
            ),
            Item(
                "purelymail",
                "Purelymail",
                "Mailboxes + domains + templates",
                "plugin",
                {
                    "plugin": "purelymail"
                },
            ),
        ]

    if key == "plugin":
        plugin = screen.context[
            "plugin"
        ]

        if plugin == "porkbun":
            return [
                Item(
                    "domains",
                    "List Real Domains",
                ),
                Item(
                    "api_key",
                    "Set Porkbun API Key",
                ),
                Item(
                    "secret_key",
                    "Set Porkbun Secret Key",
                ),
            ]

        if plugin == "purelymail":
            return [
                Item(
                    "users",
                    "List Real Mailboxes",
                ),
                Item(
                    "domains",
                    "List Real Domains",
                ),
                Item(
                    "create",
                    "Create Mailbox",
                ),
                Item(
                    "template",
                    "Create from Template",
                    "support / alerts / noreply / admin / hello",
                ),
                Item(
                    "delete",
                    "Delete Mailbox",
                ),
                Item(
                    "credit",
                    "Account Credit",
                ),
                Item(
                    "token",
                    "Set Purelymail API Token",
                ),
            ]

    if key == "channels":
        result = [
            Item(
                "__add__",
                "+ Add Channel",
            )
        ]

        for name, value in channels_data().items():
            enabled = bool(
                value.get(
                    "enabled",
                    False,
                )
            )

            purposes = value.get(
                "purposes",
                [],
            )

            result.append(
                Item(
                    name,
                    name,
                    (
                        (
                            "ON"
                            if enabled
                            else "OFF"
                        )
                        + (
                            " • "
                            + ", ".join(
                                purposes
                            )
                            if purposes
                            else ""
                        )
                    ),
                    "channel",
                    {
                        "channel": name,
                    },
                )
            )

        return result

    if key == "channel":
        channel = screen.context[
            "channel"
        ]

        value = channels_data().get(
            channel,
            {},
        )

        enabled = bool(
            value.get(
                "enabled",
                False,
            )
        )

        return [
            Item(
                "enabled",
                (
                    "Disable Channel"
                    if enabled
                    else "Enable Channel"
                ),
            ),
            Item(
                "purposes",
                "Configure Uses",
                "SPACE selects multiple",
            ),
            Item(
                "remove",
                "Remove Channel",
            ),
        ]

    if key == "projects":
        return [
            Item(
                str(path),
                path.name,
                str(path),
                "project",
                {
                    "project": str(path)
                },
            )
            for path in projects()
        ]

    if key == "project":
        project = screen.context[
            "project"
        ]

        return [
            Item(
                "agents",
                "Link AI Agents",
                "SPACE selects multiple",
            ),
            Item(
                "channels",
                "Link Channels",
                "SPACE selects multiple",
            ),
            Item(
                "shell",
                "Open Project Shell",
                project,
            ),
        ]

    if key == "voice":
        status, mode = voice_state()

        return [
            Item(
                "talk",
                "Talk Now",
                status,
            ),
            Item(
                "wake",
                "Wake Word",
                mode,
            ),
            Item(
                "ptt",
                "Push to Talk",
            ),
            Item(
                "always",
                "Always Listening / 24/7",
            ),
            Item(
                "stop",
                "Stop Voice Agent",
            ),
            Item(
                "settings",
                "Voice Settings",
            ),
        ]

    if key == "network":
        network = network_cached()

        return [
            Item(
                "refresh",
                "Refresh Network",
                str(
                    network.get(
                        "updated_at",
                        "never",
                    )
                ),
            ),
            Item(
                "matrix",
                "Show Agent Matrix",
            ),
            Item(
                "raw",
                "Show Network JSON",
            ),
        ]

    if key in ("settings", "system"):
        from .settings import get_all_settings
        st = get_all_settings()
        auto_check_enabled = st.get("update", {}).get("auto_check", True)
        update_stat = st.get("update", {}).get("status", {})
        update_desc = (
            f"Update Available ({update_stat.get('commits_behind', 0)} commits behind)"
            if update_stat.get("update_available")
            else "Up to date"
        )
        return [
            Item(
                "doctor",
                "APX Doctor",
                "Diagnose nodes, credentials, and configuration",
            ),
            Item(
                "update",
                "Update APX",
                f"{update_desc} • check and apply updates",
            ),
            Item(
                "toggle_auto_update",
                "Auto-Check for Updates",
                f"{'Enabled' if auto_check_enabled else 'Disabled'} (checks on launch)",
            ),
            Item(
                "show_settings",
                "Show Settings & Paths",
                "Display environment, runtime, and state paths",
            ),
            Item(
                "native",
                "Native APX Menu",
                "Classic APX interactive menu",
            ),
            Item(
                "push",
                "Publish APX to VPS",
                "Push wheel build to remote fleet",
            ),
        ]

    if key == "select":
        return [
            Item(
                option,
                option,
            )
            for option in screen.context.get(
                "options",
                [],
            )
        ]

    return []


STYLE = Style.from_dict(
    {
        "title": "bold",
        "breadcrumb": "italic",
        "selected": "reverse",
        "muted": "ansibrightblack",
        "accent": "bold",
        "checked": "bold",
        "footer": "ansibrightblack",
        "danger": "bold",
    }
)


class APXTUI:
    def __init__(self) -> None:
        self.stack = [
            Screen(
                "main",
                "APX",
            )
        ]

        self.quit = False

    @property
    def screen(self) -> Screen:
        return self.stack[-1]

    def breadcrumb(self) -> str:
        return "  ›  ".join(
            screen.title
            for screen in self.stack
        )

    def render(self) -> FormattedText:
        screen = self.screen

        items = current_screen_items(
            screen
        )

        if items:
            screen.index = max(
                0,
                min(
                    screen.index,
                    len(items) - 1,
                ),
            )
        else:
            screen.index = 0

        columns, rows = shutil.get_terminal_size(
            (100, 30)
        )

        visible = max(
            8,
            rows - 9,
        )

        start = max(
            0,
            screen.index
            - visible // 2,
        )

        end = min(
            len(items),
            start + visible,
        )

        if end - start < visible:
            start = max(
                0,
                end - visible,
            )

        output: list[
            tuple[str, str]
        ] = []

        output.extend(
            [
                (
                    "class:title",
                    "APX\n",
                ),
                (
                    "class:breadcrumb",
                    self.breadcrumb()
                    + "\n",
                ),
                (
                    "",
                    "─"
                    * min(
                        columns,
                        80,
                    )
                    + "\n\n",
                ),
            ]
        )

        if not items:
            output.append(
                (
                    "class:muted",
                    "  Nothing here yet.\n",
                )
            )

        for index in range(
            start,
            end,
        ):
            item = items[index]

            selected = (
                index == screen.index
            )

            checked = (
                item.key
                in screen.multi
            )

            marker = (
                "[✓]"
                if checked
                else "[ ]"
            )

            pointer = (
                "›"
                if selected
                else " "
            )

            style = (
                "class:selected"
                if selected
                else ""
            )

            line = (
                f"{pointer} "
                f"{marker} "
                f"{item.label}"
            )

            if item.detail:
                pad = max(
                    2,
                    36 - len(
                        item.label
                    ),
                )

                line += (
                    " " * pad
                    + item.detail
                )

            output.append(
                (
                    style,
                    line[: max(
                        20,
                        columns - 1,
                    )]
                    + "\n",
                )
            )

        output.extend(
            [
                (
                    "",
                    "\n",
                ),
                (
                    "class:footer",
                    "↑↓ move   "
                    "SPACE select   "
                    "ENTER open/toggle   "
                    "ESC/← back   "
                    "R refresh   "
                    "Q quit\n",
                ),
            ]
        )

        return FormattedText(
            output
        )

    def run_frame(self) -> tuple[
        str,
        Any,
    ]:
        control = FormattedTextControl(
            text=self.render,
            focusable=True,
        )

        window = Window(
            content=control,
            wrap_lines=False,
            always_hide_cursor=True,
        )

        root = HSplit(
            [
                window,
            ]
        )

        kb = KeyBindings()

        @kb.add("up")
        @kb.add("k")
        def _up(event) -> None:
            items = current_screen_items(
                self.screen
            )

            if items:
                self.screen.index = (
                    self.screen.index
                    - 1
                ) % len(items)

            event.app.invalidate()

        @kb.add("down")
        @kb.add("j")
        def _down(event) -> None:
            items = current_screen_items(
                self.screen
            )

            if items:
                self.screen.index = (
                    self.screen.index
                    + 1
                ) % len(items)

            event.app.invalidate()

        @kb.add("space")
        def _space(event) -> None:
            items = current_screen_items(
                self.screen
            )

            if not items:
                return

            item = items[
                self.screen.index
            ]

            if (
                item.key
                in self.screen.multi
            ):
                self.screen.multi.remove(
                    item.key
                )
            else:
                self.screen.multi.add(
                    item.key
                )

            event.app.invalidate()

        @kb.add("enter")
        def _enter(event) -> None:
            items = current_screen_items(
                self.screen
            )

            if not items:
                return

            item = items[
                self.screen.index
            ]

            event.app.exit(
                result=(
                    "enter",
                    item,
                )
            )

        @kb.add("escape")
        @kb.add("left")
        @kb.add("backspace")
        def _back(event) -> None:
            event.app.exit(
                result=(
                    "back",
                    None,
                )
            )

        @kb.add("r")
        def _refresh(event) -> None:
            event.app.exit(
                result=(
                    "refresh",
                    None,
                )
            )

        @kb.add("q")
        def _quit(event) -> None:
            event.app.exit(
                result=(
                    "quit",
                    None,
                )
            )

        @kb.add("c-c")
        def _ctrl_c(event) -> None:
            if len(
                self.stack
            ) > 1:
                event.app.exit(
                    result=(
                        "back",
                        None,
                    )
                )
            else:
                event.app.exit(
                    result=(
                        "quit",
                        None,
                    )
                )

        application = Application(
            layout=Layout(
                root,
                focused_element=window,
            ),
            key_bindings=kb,
            style=STYLE,
            full_screen=True,
            mouse_support=False,
        )

        result = application.run()

        return result or (
            "quit",
            None,
        )

    def push(
        self,
        key: str,
        title: str,
        *,
        context: dict[str, Any]
        | None = None,
        multi: set[str]
        | None = None,
    ) -> None:
        self.stack.append(
            Screen(
                key,
                title,
                context=context or {},
                multi=set(
                    multi or set()
                ),
            )
        )

    def back(self) -> None:
        if len(
            self.stack
        ) > 1:
            self.stack.pop()
        else:
            self.quit = True

    def choose_links(
        self,
        *,
        owner_type: str,
        owner: str,
        link_type: str,
    ) -> None:
        links = links_data()

        record = (
            links
            .setdefault(
                owner_type,
                {},
            )
            .setdefault(
                owner,
                {},
            )
        )

        selected = set(
            record.get(
                link_type,
                [],
            )
        )

        if link_type == "channels":
            options = list(
                channels_data().keys()
            )

        elif link_type == "projects":
            options = [
                str(path)
                for path in projects()
            ]

        elif link_type == "agents":
            options = [
                (
                    f"{record['machine']}:"
                    f"{record['agent']}"
                )
                for record in agent_records()
                if record.get(
                    "installed"
                )
            ]

        else:
            options = []

        self.push(
            "select",
            f"Select {link_type.title()}",
            context={
                "owner_type": (
                    owner_type
                ),
                "owner": owner,
                "link_type": (
                    link_type
                ),
                "options": options,
            },
            multi=selected,
        )

    def save_select(self) -> None:
        screen = self.screen

        owner_type = screen.context[
            "owner_type"
        ]
        owner = screen.context[
            "owner"
        ]
        link_type = screen.context[
            "link_type"
        ]

        links = links_data()

        record = (
            links
            .setdefault(
                owner_type,
                {},
            )
            .setdefault(
                owner,
                {},
            )
        )

        record[
            link_type
        ] = sorted(
            screen.multi
        )

        save_links(
            links
        )

        self.back()

    def open_agent_session(
        self,
        machine: str,
        agent: str,
    ) -> None:
        config = (
            network_cached()
            .get(
                "machines",
                {},
            )
            .get(
                machine,
                {},
            )
        )

        target = config.get(
            "target"
        )

        terminal_dir = (
            SHARE / "terminal"
        )

        terminal_dir.mkdir(
            parents=True,
            exist_ok=True,
        )

        command_file = (
            terminal_dir
            / "agent-session.command"
        )

        if machine == "mbp":
            command = (
                f"exec {shlex.quote(agent)}"
            )
        else:
            command = (
                "exec ssh -t "
                + shlex.quote(
                    str(target)
                )
                + " "
                + shlex.quote(
                    f"exec {agent}"
                )
            )

        command_file.write_text(
            "#!/bin/bash\n"
            "clear\n"
            + command
            + "\n"
        )

        os.chmod(
            command_file,
            0o700,
        )

        subprocess.Popen(
            [
                "open",
                "-a",
                "Terminal",
                str(
                    command_file
                ),
            ],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )

    def standing_toggle(
        self,
        machine: str,
        agent: str,
    ) -> None:
        identifier = (
            f"{machine}:{agent}"
        )

        value = standing_data()

        record = value.setdefault(
            identifier,
            {},
        )

        record["standing"] = not bool(
            record.get(
                "standing",
                False,
            )
        )

        save_standing(
            value
        )

        print()
        print(
            f"{identifier}: "
            + (
                "standing"
                if record["standing"]
                else "normal"
            )
        )

        pause()

    def standing_stop(
        self,
        machine: str,
        agent: str,
    ) -> None:
        command = [
            "tmux",
            "kill-session",
            "-t",
            f"apx-{agent}",
        ]

        try:
            run_remote(
                machine,
                command,
            )
        except Exception as exc:
            print(exc)

        pause()

    def standing_attach(
        self,
        machine: str,
        agent: str,
    ) -> None:
        terminal_dir = (
            SHARE / "terminal"
        )

        terminal_dir.mkdir(
            parents=True,
            exist_ok=True,
        )

        path = (
            terminal_dir
            / "standing-agent.command"
        )

        network = network_cached()

        target = (
            network
            .get(
                "machines",
                {},
            )
            .get(
                machine,
                {},
            )
            .get(
                "target"
            )
        )

        if machine == "mbp":
            command = (
                f"exec tmux attach -t "
                f"apx-{agent}"
            )
        else:
            command = (
                "exec ssh -t "
                + shlex.quote(
                    str(target)
                )
                + " "
                + shlex.quote(
                    f"tmux attach -t "
                    f"apx-{agent}"
                )
            )

        path.write_text(
            "#!/bin/bash\n"
            "clear\n"
            + command
            + "\n"
        )

        os.chmod(
            path,
            0o700,
        )

        subprocess.Popen(
            [
                "open",
                "-a",
                "Terminal",
                str(path),
            ]
        )

    def handle_enter(
        self,
        item: Item,
    ) -> None:
        screen = self.screen

        if screen.key == "select":
            if self.handle_select_channel_purposes():
                return
            self.save_select()
            return

        if screen.key == "main":
            titles = {
                "computers": "Computers",
                "agents": "AI Agents",
                "credentials": "Passwords & API Keys",
                "plugins": "Plugins & Services",
                "channels": "Channels",
                "projects": "Projects",
                "voice": "Voice Agent",
                "network": "Network",
                "system": "System",
            }

            self.push(
                item.key,
                titles.get(
                    item.key,
                    item.label,
                ),
            )
            return

        if screen.key == "computers":
            self.push(
                "computer",
                item.label,
                context={
                    "machine": (
                        item.data[
                            "machine"
                        ]
                    )
                },
            )
            return

        if screen.key == "computer":
            machine = screen.context[
                "machine"
            ]

            network = network_cached()

            machine_info = (
                network
                .get(
                    "machines",
                    {},
                )
                .get(
                    machine,
                    {},
                )
            )

            if item.key == "agents":
                self.push(
                    "agents",
                    "AI Agents",
                )

            elif item.key == "shell":
                target = machine_info.get(
                    "target"
                )

                if machine == "mbp":
                    os.system(
                        "open -a Terminal"
                    )
                else:
                    os.system(
                        "open -a Terminal "
                        + shlex.quote(
                            str(
                                SHARE
                                / "terminal"
                                / "remote-shell.command"
                            )
                        )
                    )

                    path = (
                        SHARE
                        / "terminal"
                        / "remote-shell.command"
                    )

                    path.parent.mkdir(
                        parents=True,
                        exist_ok=True,
                    )

                    path.write_text(
                        "#!/bin/bash\n"
                        f"exec ssh -t "
                        f"{shlex.quote(str(target))}\n"
                    )

                    os.chmod(
                        path,
                        0o700,
                    )

                    subprocess.Popen(
                        [
                            "open",
                            "-a",
                            "Terminal",
                            str(path),
                        ]
                    )

            elif item.key == "doctor":
                if machine == "mbp":
                    native(
                        "doctor"
                    )
                else:
                    run_remote(
                        machine,
                        [
                            "apx",
                            "doctor",
                        ],
                        tty=True,
                    )
                pause()

            elif item.key == "version":
                if machine == "mbp":
                    native(
                        "--version"
                    )
                else:
                    run_remote(
                        machine,
                        [
                            "apx",
                            "--version",
                        ],
                    )
                pause()

            elif item.key == "refresh":
                value = network_refresh()
                print(
                    json.dumps(
                        value,
                        indent=2,
                    )
                )
                pause()

            return

        if screen.key == "agents":
            self.push(
                "agent",
                item.label,
                context=item.data,
            )
            return

        if screen.key == "agent":
            machine = screen.context[
                "machine"
            ]
            agent = screen.context[
                "agent"
            ]

            identifier = (
                f"{machine}:{agent}"
            )

            if item.key == "start":
                self.open_agent_session(
                    machine,
                    agent,
                )

            elif item.key == "standing":
                self.standing_toggle(
                    machine,
                    agent,
                )

            elif item.key == "attach":
                self.standing_attach(
                    machine,
                    agent,
                )

            elif item.key == "stop":
                self.standing_stop(
                    machine,
                    agent,
                )

            elif item.key == "project":
                self.choose_links(
                    owner_type="agents",
                    owner=identifier,
                    link_type="projects",
                )

            elif item.key == "channels":
                self.choose_links(
                    owner_type="agents",
                    owner=identifier,
                    link_type="channels",
                )

            elif item.key == "refresh":
                value = network_refresh()
                print(
                    json.dumps(
                        value,
                        indent=2,
                    )
                )
                pause()

            return

        if screen.key == "credentials":
            if item.key == "__add__":
                identifier = input(
                    "Credential name: "
                ).strip()

                if identifier:
                    native(
                        "secret",
                        "set",
                        identifier,
                    )

                    links = links_data()

                    links[
                        "credentials"
                    ].setdefault(
                        identifier,
                        {},
                    )

                    save_links(
                        links
                    )

                return

            self.push(
                "credential",
                item.label,
                context=item.data,
            )
            return

        if screen.key == "credential":
            identifier = screen.context[
                "credential"
            ]

            if item.key == "set":
                native(
                    "secret",
                    "set",
                    identifier,
                )
                pause()

            elif item.key == "reveal":
                native(
                    "secret",
                    "reveal",
                    identifier,
                )
                pause()

            elif item.key == "remove":
                print(
                    f"Revoking {identifier}..."
                )

                native(
                    "credential",
                    "revoke",
                    identifier,
                )

                links = links_data()

                links[
                    "credentials"
                ].pop(
                    identifier,
                    None,
                )

                save_links(
                    links
                )

                pause()

            elif item.key in (
                "agents",
                "projects",
                "channels",
            ):
                self.choose_links(
                    owner_type="credentials",
                    owner=identifier,
                    link_type=item.key,
                )

            return

        if screen.key == "plugins":
            self.push(
                "plugin",
                item.label,
                context=item.data,
            )
            return

        if screen.key == "plugin":
            plugin = screen.context[
                "plugin"
            ]

            if plugin == "porkbun":
                if item.key == "domains":
                    try:
                        domains = (
                            porkbun_domains()
                        )

                        table = Table(
                            title="Porkbun Domains"
                        )

                        table.add_column(
                            "Domain"
                        )
                        table.add_column(
                            "Status"
                        )
                        table.add_column(
                            "Expires"
                        )

                        for domain in domains:
                            if isinstance(
                                domain,
                                dict,
                            ):
                                table.add_row(
                                    str(
                                        domain.get(
                                            "domain",
                                            domain.get(
                                                "name",
                                                "",
                                            ),
                                        )
                                    ),
                                    str(
                                        domain.get(
                                            "status",
                                            "",
                                        )
                                    ),
                                    str(
                                        domain.get(
                                            "expireDate",
                                            domain.get(
                                                "expiration",
                                                "",
                                            ),
                                        )
                                    ),
                                )
                            else:
                                table.add_row(
                                    str(domain),
                                    "",
                                    "",
                                )

                        console.print(
                            table
                        )

                    except Exception as exc:
                        console.print(
                            f"[bold]Porkbun error:[/bold] {exc}"
                        )

                    pause()

                elif item.key == "api_key":
                    native(
                        "secret",
                        "set",
                        "porkbun_api_key",
                    )
                    pause()

                elif item.key == "secret_key":
                    native(
                        "secret",
                        "set",
                        "porkbun_secret_key",
                    )
                    pause()

                return

            if plugin == "purelymail":
                if item.key == "users":
                    try:
                        users = (
                            purelymail_users()
                        )

                        table = Table(
                            title="Purelymail Mailboxes"
                        )

                        table.add_column(
                            "Email"
                        )

                        for user in users:
                            table.add_row(
                                user
                            )

                        console.print(
                            table
                        )

                    except Exception as exc:
                        console.print(
                            f"[bold]Purelymail error:[/bold] {exc}"
                        )

                    pause()

                elif item.key == "domains":
                    try:
                        value = (
                            purelymail_domains()
                        )

                        console.print_json(
                            data=value
                        )
                    except Exception as exc:
                        console.print(
                            f"[bold]Purelymail error:[/bold] {exc}"
                        )

                    pause()

                elif item.key in (
                    "create",
                    "template",
                ):
                    template = ""

                    if item.key == "template":
                        print()
                        print(
                            "1  support"
                        )
                        print(
                            "2  alerts"
                        )
                        print(
                            "3  noreply"
                        )
                        print(
                            "4  admin"
                        )
                        print(
                            "5  hello"
                        )
                        print()

                        choice = input(
                            "Template: "
                        ).strip()

                        template = {
                            "1": "support",
                            "2": "alerts",
                            "3": "noreply",
                            "4": "admin",
                            "5": "hello",
                        }.get(
                            choice,
                            "",
                        )

                    local = (
                        template
                        or input(
                            "Mailbox name: "
                        ).strip()
                    )

                    domain = input(
                        "Domain: "
                    ).strip()

                    password = getpass.getpass(
                        "Mailbox password: "
                    )

                    if (
                        local
                        and domain
                        and password
                    ):
                        try:
                            result = (
                                purelymail_create_user(
                                    local_part=local,
                                    domain=domain,
                                    password=password,
                                    send_welcome=True,
                                )
                            )

                            console.print_json(
                                data=result
                            )
                        except Exception as exc:
                            console.print(
                                f"[bold]Purelymail error:[/bold] {exc}"
                            )

                    pause()

                elif item.key == "delete":
                    email = input(
                        "Mailbox to delete: "
                    ).strip()

                    confirm = input(
                        f"Type DELETE {email}: "
                    ).strip()

                    if confirm == (
                        f"DELETE {email}"
                    ):
                        try:
                            result = (
                                purelymail_delete_user(
                                    email
                                )
                            )

                            console.print_json(
                                data=result
                            )
                        except Exception as exc:
                            console.print(
                                f"[bold]Purelymail error:[/bold] {exc}"
                            )

                    pause()

                elif item.key == "credit":
                    try:
                        console.print_json(
                            data=(
                                purelymail_credit()
                            )
                        )
                    except Exception as exc:
                        console.print(
                            f"[bold]Purelymail error:[/bold] {exc}"
                        )

                    pause()

                elif item.key == "token":
                    native(
                        "secret",
                        "set",
                        "purelymail_credential",
                    )
                    pause()

                return

        if screen.key == "channels":
            if item.key == "__add__":
                name = input(
                    "Channel name: "
                ).strip()

                if name:
                    kind = (
                        input(
                            "Channel type: "
                        ).strip()
                        or name
                    )

                    value = (
                        channels_data()
                    )

                    value[name] = {
                        "type": kind,
                        "enabled": True,
                        "purposes": [],
                    }

                    save_channels(
                        value
                    )

                return

            self.push(
                "channel",
                item.label,
                context=item.data,
            )
            return

        if screen.key == "channel":
            channel = screen.context[
                "channel"
            ]

            value = channels_data()

            record = value.setdefault(
                channel,
                {
                    "type": channel,
                    "enabled": False,
                    "purposes": [],
                },
            )

            if item.key == "enabled":
                record["enabled"] = not bool(
                    record.get(
                        "enabled",
                        False,
                    )
                )

                save_channels(
                    value
                )

            elif item.key == "purposes":
                purposes = [
                    "alerts",
                    "approvals",
                    "agent-replies",
                    "voice-results",
                    "status",
                    "deployments",
                    "security",
                ]

                self.push(
                    "select",
                    "Channel Uses",
                    context={
                        "owner_type": (
                            "__channel__"
                        ),
                        "owner": channel,
                        "link_type": (
                            "purposes"
                        ),
                        "options": purposes,
                    },
                    multi=set(
                        record.get(
                            "purposes",
                            [],
                        )
                    ),
                )

            elif item.key == "remove":
                value.pop(
                    channel,
                    None,
                )

                save_channels(
                    value
                )

                self.back()

            return

        if screen.key == "projects":
            self.push(
                "project",
                item.label,
                context=item.data,
            )
            return

        if screen.key == "project":
            project = screen.context[
                "project"
            ]

            if item.key == "agents":
                self.choose_links(
                    owner_type="projects",
                    owner=project,
                    link_type="agents",
                )

            elif item.key == "channels":
                self.choose_links(
                    owner_type="projects",
                    owner=project,
                    link_type="channels",
                )

            elif item.key == "shell":
                path = (
                    SHARE
                    / "terminal"
                    / "project.command"
                )

                path.parent.mkdir(
                    parents=True,
                    exist_ok=True,
                )

                path.write_text(
                    "#!/bin/bash\n"
                    f"cd {shlex.quote(project)}\n"
                    "exec $SHELL -l\n"
                )

                os.chmod(
                    path,
                    0o700,
                )

                subprocess.Popen(
                    [
                        "open",
                        "-a",
                        "Terminal",
                        str(path),
                    ]
                )

            return

        if screen.key == "voice":
            if item.key == "talk":
                subprocess.call(
                    [
                        str(
                            SHARE
                            / "voice"
                            / "run"
                        ),
                        "talk",
                    ]
                )

            elif item.key == "wake":
                subprocess.call(
                    [
                        str(
                            SHARE
                            / "voice"
                            / "run"
                        ),
                        "mode",
                        "wake-word",
                    ]
                )

            elif item.key == "ptt":
                subprocess.call(
                    [
                        str(
                            SHARE
                            / "voice"
                            / "run"
                        ),
                        "mode",
                        "push-to-talk",
                    ]
                )

            elif item.key == "always":
                subprocess.call(
                    [
                        str(
                            SHARE
                            / "voice"
                            / "run"
                        ),
                        "mode",
                        "always",
                    ]
                )

            elif item.key == "stop":
                subprocess.call(
                    [
                        str(
                            SHARE
                            / "voice"
                            / "run"
                        ),
                        "stop",
                    ]
                )

            elif item.key == "settings":
                subprocess.call(
                    [
                        str(
                            SHARE
                            / "voice"
                            / "run"
                        ),
                        "interactive",
                    ]
                )

            return

        if screen.key == "network":
            if item.key == "refresh":
                value = (
                    network_refresh()
                )

                console.print_json(
                    data=value
                )
                pause()

            elif item.key == "matrix":
                network = (
                    network_cached()
                )

                table = Table(
                    title="APX Agent Matrix"
                )

                table.add_column(
                    "Computer"
                )
                table.add_column(
                    "Online"
                )
                table.add_column(
                    ""
                )
                table.add_column(
                    "Codex"
                )

                for machine, info in (
                    network
                    .get(
                        "machines",
                        {},
                    )
                    .items()
                ):
                    agents = info.get(
                        "agents",
                        {},
                    )

                    def state(
                        agent: str,
                    ) -> str:
                        record = agents.get(
                            agent,
                            {},
                        )

                        if not info.get(
                            "online"
                        ):
                            return "OFFLINE"

                        if not record.get(
                            "installed"
                        ):
                            return "MISSING"

                        if record.get(
                            "processes",
                            0,
                        ):
                            return "RUNNING"

                        return "READY"

                    table.add_row(
                        info.get(
                            "name",
                            machine,
                        ),
                        (
                            "YES"
                            if info.get(
                                "online"
                            )
                            else "NO"
                        ),
                        state(
                            ""
                        ),
                        state(
                            "codex"
                        ),
                    )

                console.print(
                    table
                )
                pause()

            elif item.key == "raw":
                console.print_json(
                    data=(
                        network_cached()
                    )
                )
                pause()

            return

        if screen.key in ("settings", "system"):
            if item.key == "doctor":
                native(
                    "doctor"
                )
                pause()

            elif item.key == "native":
                native(
                    "menu"
                )

            elif item.key == "update":
                native(
                    "settings",
                    "update",
                )
                pause()

            elif item.key == "toggle_auto_update":
                from .settings import get_all_settings, set_setting
                st = get_all_settings()
                curr = st.get("update", {}).get("auto_check", True)
                set_setting("settings.auto_update_check", "false" if curr else "true")

            elif item.key == "show_settings":
                native(
                    "settings"
                )
                pause()

            elif item.key == "push":
                native(
                    "settings",
                    "update",
                    "push",
                )
                pause()

            return

    def handle_select_channel_purposes(
        self,
    ) -> bool:
        screen = self.screen

        if (
            screen.key
            != "select"
            or screen.context.get(
                "owner_type"
            )
            != "__channel__"
        ):
            return False

        channel = screen.context[
            "owner"
        ]

        value = channels_data()

        record = value.setdefault(
            channel,
            {
                "type": channel,
                "enabled": True,
                "purposes": [],
            },
        )

        record["purposes"] = sorted(
            screen.multi
        )

        save_channels(
            value
        )

        self.back()
        return True

    def run(self) -> int:
        while not self.quit:
            action, payload = (
                self.run_frame()
            )

            if action == "quit":
                break

            if action == "back":
                self.back()
                continue

            if action == "refresh":
                if self.screen.key in (
                    "computers",
                    "agents",
                    "network",
                ):
                    print(
                        "Refreshing APX network..."
                    )

                    network_refresh()

                continue

            if action == "enter":
                if self.screen.key == "select":
                    if (
                        self.handle_select_channel_purposes()
                    ):
                        continue

                try:
                    self.handle_enter(
                        payload
                    )
                except (
                    EOFError,
                    KeyboardInterrupt,
                ):
                    pass

        return 0


def snapshot() -> int:
    network = network_cached()

    voice_status, voice_mode = (
        voice_state()
    )

    machines = network.get(
        "machines",
        {},
    )

    print("APX")
    print("===")
    print()
    print(
        f"Computers       "
        f"{sum(1 for m in machines.values() if m.get('online'))}"
        f"/{len(machines)} online"
    )
    print(
        "AI Agents       "
        f"{sum(1 for a in agent_records() if a.get('installed'))} installed"
    )
    print(
        "Voice Agent     "
        f"{voice_status} • {voice_mode}"
    )
    print(
        "Credentials     "
        f"{len(credential_ids())}"
    )
    print(
        "Channels        "
        f"{len(channels_data())}"
    )
    print()

    return 0


def main() -> int:
    if "--snapshot" in sys.argv:
        return snapshot()

    try:
        return APXTUI().run()
    except (
        EOFError,
        KeyboardInterrupt,
    ):
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
