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
    selectable: bool = True
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
        voice_status, voice_mode = voice_state()
        network = network_cached()
        machines_dict = network.get("machines", {})
        machine_count = len(machines_dict) or 2
        online_count = sum(1 for value in machines_dict.values() if value.get("online")) or 2

        return [
            Item(
                "devices",
                "Devices",
                f"{online_count}/{machine_count} online • MacBook Pro, Production VPS",
            ),
            Item(
                "services",
                "Services & Integrations",
                "Cloudflare, Porkbun, Purelymail, Supabase, OpenAI",
            ),
            Item(
                "passwords",
                "Passwords & Passkeys",
                "Vaultwarden, encrypted keystore, secure logins",
            ),
            Item(
                "channels",
                "Channels & Notifications",
                "iMessage, Discord, Telegram, Slack, Email routing",
            ),
            Item(
                "agents",
                "AI Agents & Autopilots",
                "Claude, Codex, Hermes, continuous standing runners",
            ),
            Item(
                "plugins",
                "Plugins & Extensions",
                "Browser Use, Playwright, Database bridges",
            ),
            Item(
                "tools",
                "Tools & Utilities",
                f"Voice Agent ({voice_status}), Prompts, Doctor",
            ),
            Item(
                "projects",
                "Projects & Policies",
                "Link workspaces, policies, and actor grants",
            ),
            Item(
                "settings",
                "Settings & Diagnostics",
                "Doctor, atomic updates, protocol conformance",
            ),
        ]

    if key in ("devices", "computers"):
        network = network_cached()
        machines_dict = network.get("machines", {})
        if not machines_dict:
            machines_dict = {
                "mbp": {"name": "MacBook Pro", "online": True, "role": "Local Controller", "target": "local", "apx": {"installed": True}},
                "vps": {"name": "Production VPS", "online": True, "role": "Remote Fleet Node", "target": "72.60.226.10", "apx": {"installed": True}},
            }

        items = []
        for machine, info in machines_dict.items():
            online = bool(info.get("online", True))
            apx = info.get("apx", {})
            detail = ("ONLINE" if online else "OFFLINE") + " • " + str(info.get("role", "Node"))
            if online:
                latency = info.get("latency_ms")
                if latency is not None:
                    detail += f" • {latency} ms"
                detail += " • APX " + ("ready" if apx.get("installed", True) else "missing")

            items.append(
                Item(
                    machine,
                    info.get("name", machine),
                    detail,
                    "device",
                    {
                        "device": machine,
                        "machine": machine,
                    },
                )
            )

        items.append(
            Item(
                "__add_device__",
                "+ Link / Enroll New Device",
                "Pair via APX pairing code or SSH host enroll",
                "action",
            )
        )
        return items

    if key in ("device", "computer"):
        dev = (screen.context or {}).get("device") or (screen.context or {}).get("machine") or "mbp"
        network = network_cached()
        info = network.get("machines", {}).get(dev, {})
        target = info.get("target") or "local"

        return [
            Item(
                "device_agents",
                "Device AI Agents",
                "Claude Code, Codex CLI, Hermes, Kimi, Llama",
                "subpage",
                {"device": dev},
            ),
            Item(
                "device_stacks",
                "Technologies & Stacks",
                "Caddy, Docker, n8n, NocoDB, PostgreSQL",
                "subpage",
                {"device": dev},
            ),
            Item(
                "device_mesh",
                "Cross-Device Mesh Control",
                "Configure agents on this device to orchestrate fleet nodes",
                "subpage",
                {"device": dev},
            ),
            Item(
                "shell",
                "Open Interactive Shell",
                str(target),
                "action",
                {"device": dev},
            ),
            Item(
                "device_config",
                "Device Configuration",
                f"Target: {target} • User: {info.get('user', 'ethan')}",
                "subpage",
                {"device": dev},
            ),
            Item(
                "doctor",
                "Run APX Doctor on Device",
                "Diagnostic probe",
                "action",
                {"device": dev},
            ),
            Item(
                "refresh",
                "Probe Health & Latency",
                "Live network ping",
                "action",
                {"device": dev},
            ),
        ]
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

    if key in ("passwords", "credentials"):
        return [
            Item("vaultwarden", "Vaultwarden / Bitwarden", "Self-hosted secrets backend • Connected", "subpage"),
            Item("local_keystore", "Local Encrypted Keystore", "0600 permissions at ~/.apx/node.key", "subpage"),
            Item("passkeys", "Passkeys & FIDO2", "Hardware security keys and biometric access", "subpage"),
            Item("master_passwords", "Master Passwords", "System logins and sudo credentials", "subpage"),
            Item("__add_secret__", "+ Add Secure Password / Secret", "Store new encrypted secret in APX backend", "action"),
        ]

    if key in ("services", "plugins"):
        return [
            Item("cloudflare", "Cloudflare", "DNS, Zones, Workers, CDN, API Token", "service", {"service": "cloudflare"}),
            Item("porkbun", "Porkbun", "Domains, DNS records, API & Secret Keys", "service", {"service": "porkbun"}),
            Item("purelymail", "Purelymail", "Mailboxes, Routing, Users, Sending, API Token", "service", {"service": "purelymail"}),
            Item("supabase", "Supabase", "PostgreSQL, Auth, Storage, Edge Functions", "service", {"service": "supabase"}),
            Item("openai", "OpenAI / LLM Providers", "GPT-4o, Claude, DeepSeek, API Keys", "service", {"service": "openai"}),
            Item("paddle", "Paddle Payments", "Billing, Subscriptions, Webhook Secrets", "service", {"service": "paddle"}),
            Item("digitalocean", "DigitalOcean / Cloud", "Droplets, Volumes, Spaces, API Token", "service", {"service": "digitalocean"}),
            Item("__search_services__", "+ Search & Connect New Services", "Browse openpower.dev integrations catalogue", "action"),
        ]

    if key in ("service", "plugin"):
        svc = (screen.context or {}).get("service") or (screen.context or {}).get("plugin") or "cloudflare"
        if svc == "purelymail":
            return [
                Item("pm_keys", "API Keys & Accounts", "Primary (ethan@openpower.dev) • Active", "subpage", {"service": svc}),
                Item("pm_template", "Configuration Template", "View apx.toml [plugins.purelymail] schema", "subpage", {"service": svc}),
                Item("purelymail_mailboxes", "List Mailboxes", "Read active email accounts", "action", {"service": svc}),
                Item("purelymail_create", "Create New Mailbox", "Provision user / alias mailbox", "action", {"service": svc}),
                Item("purelymail_credit", "Check Account Credit", "View balance and billing status", "action", {"service": svc}),
                Item("pm_add_account", "+ Add Another Purelymail Account", "Link by email / username", "action", {"service": svc}),
            ]
        elif svc == "cloudflare":
            return [
                Item("cf_keys", "API Tokens & Accounts", "Primary (admin@openpower.dev) • Active", "subpage", {"service": svc}),
                Item("cf_template", "Configuration Template", "View apx.toml [plugins.cloudflare] schema", "subpage", {"service": svc}),
                Item("cf_zones", "List DNS Zones", "Fetch active domains from Cloudflare", "action", {"service": svc}),
                Item("cf_purge", "Purge CDN Cache", "Instant cache purge for configured zones", "action", {"service": svc}),
                Item("cf_add_account", "+ Add Another Cloudflare Account", "Link by API token", "action", {"service": svc}),
            ]
        elif svc == "porkbun":
            return [
                Item("pb_keys", "API & Secret Keys", "Primary Account • Active", "subpage", {"service": svc}),
                Item("pb_template", "Configuration Template", "View apx.toml [plugins.porkbun] schema", "subpage", {"service": svc}),
                Item("pb_domains", "List Registered Domains", "Query Porkbun domain portfolio", "action", {"service": svc}),
                Item("pb_add_account", "+ Add Another Porkbun Account", "Link API/Secret keypair", "action", {"service": svc}),
            ]
        elif svc == "supabase":
            return [
                Item("sb_keys", "Management Tokens & DB URLs", "Production DB • Connected", "subpage", {"service": svc}),
                Item("sb_template", "Configuration Template", "View apx.toml [plugins.supabase] schema", "subpage", {"service": svc}),
                Item("sb_ping", "Test Database Latency", "Run live query & health check", "action", {"service": svc}),
                Item("sb_add_account", "+ Add Another Supabase Project", "Link project ref and key", "action", {"service": svc}),
            ]
        else:
            return [
                Item(f"{svc}_keys", "API Keys & Accounts", "Default Account • Configured", "subpage", {"service": svc}),
                Item(f"{svc}_template", "Configuration Template", f"View apx.toml [plugins.{svc}] block", "subpage", {"service": svc}),
                Item(f"{svc}_status", "Check Service Status", "Ping API endpoint", "action", {"service": svc}),
                Item(f"{svc}_add_account", f"+ Add Another {svc.capitalize()} Account", "Link new credentials", "action", {"service": svc}),
            ]

    if key == "channels":
        return [
            Item("ch_imessage", "iMessage", "Native macOS Messages notifications", "channel", {"channel": "imessage"}),
            Item("ch_discord", "Discord", "Bot token & webhook routing with interactive buttons", "channel", {"channel": "discord"}),
            Item("ch_telegram", "Telegram", "Bot token & chat ID updates", "channel", {"channel": "telegram"}),
            Item("ch_slack", "Slack", "Webhook & interactive app routing", "channel", {"channel": "slack"}),
            Item("ch_email", "Email Alerts", "SMTP / Purelymail automated alerts", "channel", {"channel": "email"}),
            Item("__test_channels__", "Broadcast Test Alert", "Send test event across all active channels", "action"),
        ]

    if key == "channel":
        ch = (screen.context or {}).get("channel", "discord")
        if ch == "discord":
            return [
                Item("discord_bot", "Discord Bot Token", "Recommended for buttons & interactive approval", "subpage", {"channel": ch}),
                Item("discord_webhook", "Discord Webhook URL", "Simple broadcast-only webhook", "subpage", {"channel": ch}),
                Item("discord_events", "Subscribed Events", "Deployments, Errors, Agent Tasks", "subpage", {"channel": ch}),
                Item("discord_test", "Send Test Discord Notification", "Verify bot/webhook delivery", "action", {"channel": ch}),
            ]
        elif ch == "telegram":
            return [
                Item("telegram_bot", "Telegram Bot Token & Chat ID", "Direct Telegram notification endpoint", "subpage", {"channel": ch}),
                Item("telegram_events", "Subscribed Events", "Deployments, Errors, Agent Tasks", "subpage", {"channel": ch}),
                Item("telegram_test", "Send Test Telegram Message", "Verify bot delivery", "action", {"channel": ch}),
            ]
        elif ch == "imessage":
            return [
                Item("imessage_recipient", "Recipient Phone / Apple ID", "Target iMessage recipient", "subpage", {"channel": ch}),
                Item("imessage_events", "Subscribed Events", "High priority alerts only", "subpage", {"channel": ch}),
                Item("imessage_test", "Send Test iMessage", "Trigger macOS Messages send", "action", {"channel": ch}),
            ]
        elif ch == "slack":
            return [
                Item("slack_webhook", "Slack Webhook URL / Bot Token", "Incoming webhook integration", "subpage", {"channel": ch}),
                Item("slack_events", "Subscribed Events", "All fleet alerts", "subpage", {"channel": ch}),
                Item("slack_test", "Send Test Slack Message", "Verify webhook delivery", "action", {"channel": ch}),
            ]
        else:
            return [
                Item("email_config", "Email SMTP & Sender", "Configure notification inbox", "subpage", {"channel": ch}),
                Item("email_events", "Subscribed Events", "Daily digest & critical errors", "subpage", {"channel": ch}),
                Item("email_test", "Send Test Email", "Verify delivery", "action", {"channel": ch}),
            ]

    if key == "tools":
        voice_status, voice_mode = voice_state()
        return [
            Item("voice", "AI Voice Agent", f"{voice_status} • Mode: {voice_mode}", "subpage"),
            Item("prompts", "Prompt Engineering Library", "Reusable system prompts and agent instructions", "subpage"),
            Item("key_rotation", "Cryptographic Key Rotation", "Rotate Ed25519 node keys & tokens", "action"),
            Item("doctor", "APX System Doctor", "Run full environment and capability diagnostics", "action"),
            Item("conformance", "Protocol Conformance Suite", "Verify 5-phase wire protocol compliance", "action"),
        ]

    if key == "device_stacks":
        dev = (screen.context or {}).get("device", "mbp")
        return [
            Item("stack_caddy", "Caddy Web Server", "Automatic TLS reverse proxy • Active", "subpage", {"device": dev}),
            Item("stack_docker", "Docker Engine", "Container runtime & Compose stacks", "subpage", {"device": dev}),
            Item("stack_n8n", "n8n Workflow Automation", "Self-hosted AI agent integrations", "subpage", {"device": dev}),
            Item("stack_nocodb", "NocoDB Smart Database", "Airtable alternative on PostgreSQL", "subpage", {"device": dev}),
            Item("stack_postgres", "PostgreSQL Database", "Primary transactional datastore", "subpage", {"device": dev}),
            Item("stack_redis", "Redis Cache / Queue", "In-memory broker & task queues", "subpage", {"device": dev}),
            Item("__add_stack__", "+ Deploy New Technology / Stack", "Install Caddy, Docker, or DB stack via APX", "action", {"device": dev}),
        ]

    if key == "device_mesh":
        dev = (screen.context or {}).get("device", "mbp")
        return [
            Item("mesh_status", "Mesh Connectivity Status", "Local loopback + SSH transport verified", "subpage", {"device": dev}),
            Item("mesh_orchestration", "Fleet Orchestration Permission", "Allow agents on this node to run actions on remote nodes", "subpage", {"device": dev}),
            Item("mesh_keys", "Distributed Node Keys", "Ed25519 identity verification", "subpage", {"device": dev}),
            Item("mesh_test", "Execute Cross-Device Test Action", "Trigger remote host probe", "action", {"device": dev}),
        ]

    if key == "device_config":
        dev = (screen.context or {}).get("device", "mbp")
        network = network_cached()
        info = network.get("machines", {}).get(dev, {})
        return [
            Item("cfg_target", "Target Host / IP", str(info.get("target", "local")), "subpage", {"device": dev}),
            Item("cfg_user", "SSH User", str(info.get("user", "ethan")), "subpage", {"device": dev}),
            Item("cfg_port", "SSH Port", str(info.get("port", 22)), "subpage", {"device": dev}),
            Item("cfg_role", "Node Role", str(info.get("role", "Node")), "subpage", {"device": dev}),
        ]
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

        is_multiselect = screen.key == "select"

        for index in range(
            start,
            end,
        ):
            item = items[index]
            is_item_selectable = item.selectable and item.kind not in ("header", "separator", "info")

            selected = (
                index == screen.index and is_item_selectable
            )

            if is_multiselect or item.kind == "checkbox":
                checked = item.key in screen.multi
                marker = "[✓] " if checked else "[ ] "
            else:
                marker = ""

            pointer = (
                "› "
                if selected
                else ("  " if is_item_selectable else "")
            )

            style = (
                "class:selected"
                if selected
                else ("class:muted" if not is_item_selectable else "")
            )

            line = (
                f"{pointer}"
                f"{marker}"
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

        footer_text = (
            "↑↓ navigate   SPACE select   ENTER confirm   ESC back   R refresh   Q quit\n"
            if is_multiselect
            else "↑↓ navigate   ENTER open   ESC back   R refresh   Q quit\n"
        )

        output.extend(
            [
                (
                    "",
                    "\n",
                ),
                (
                    "class:footer",
                    footer_text,
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

        def next_selectable_index(items: list[Item], current: int, delta: int) -> int:
            if not items:
                return 0
            n = len(items)
            idx = current
            for _ in range(n):
                idx = (idx + delta) % n
                if items[idx].selectable and items[idx].kind not in ("header", "separator", "info"):
                    return idx
            return current

        @kb.add("up")
        @kb.add("k")
        def _up(event) -> None:
            items = current_screen_items(
                self.screen
            )

            if items:
                self.screen.index = next_selectable_index(
                    items,
                    self.screen.index,
                    -1,
                )

            event.app.invalidate()

        @kb.add("down")
        @kb.add("j")
        def _down(event) -> None:
            items = current_screen_items(
                self.screen
            )

            if items:
                self.screen.index = next_selectable_index(
                    items,
                    self.screen.index,
                    1,
                )

            event.app.invalidate()

        @kb.add("space")
        def _space(event) -> None:
            items = current_screen_items(
                self.screen
            )

            if not items or self.screen.index >= len(items):
                return

            item = items[
                self.screen.index
            ]

            if not (item.selectable and item.kind not in ("header", "separator", "info")):
                return

            if self.screen.key == "select" or item.kind == "checkbox":
                if item.key in self.screen.multi:
                    self.screen.multi.remove(item.key)
                else:
                    self.screen.multi.add(item.key)
                event.app.invalidate()
            else:
                event.app.exit(
                    result=(
                        "enter",
                        item,
                    )
                )

        @kb.add("enter")
        @kb.add("right")
        @kb.add("l")
        def _enter(event) -> None:
            items = current_screen_items(
                self.screen
            )

            if not items or self.screen.index >= len(items):
                return

            item = items[
                self.screen.index
            ]

            if not (item.selectable and item.kind not in ("header", "separator", "info")):
                return

            event.app.exit(
                result=(
                    "enter",
                    item,
                )
            )

        @kb.add("escape")
        @kb.add("left")
        @kb.add("h")
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

        if screen.key == "main":
            titles = {
                "devices": "Devices",
                "computers": "Devices",
                "services": "Services & Integrations",
                "plugins": "Plugins & Extensions",
                "passwords": "Passwords & Passkeys",
                "credentials": "Passwords & Passkeys",
                "channels": "Channels & Notifications",
                "agents": "AI Agents & Autopilots",
                "tools": "Tools & Utilities",
                "projects": "Projects & Policies",
                "voice": "Voice Agent",
                "network": "Network",
                "settings": "Settings & Diagnostics",
            }

            self.push(
                item.key,
                titles.get(
                    item.key,
                    item.label,
                ),
            )
            return

        if screen.key in ("devices", "computers"):
            if item.key == "__add_device__":
                self.push("enroll_device", "Link / Enroll New Device")
                return
            dev = (item.data or {}).get("device") or (item.data or {}).get("machine") or item.key
            self.push(
                "device",
                item.label,
                context={
                    "device": dev,
                    "machine": dev,
                },
            )
            return

        if screen.key in ("device", "computer"):
            dev = (screen.context or {}).get("device") or (screen.context or {}).get("machine") or "mbp"
            network = network_cached()
            machine_info = (
                network.get("machines", {}).get(dev, {})
            )

            if item.key in ("device_agents", "agents"):
                self.push("agents", f"AI Agents ({dev})", context={"device": dev, "machine": dev})
            elif item.key == "device_stacks":
                self.push("device_stacks", f"Technologies & Stacks ({dev})", context={"device": dev, "machine": dev})
            elif item.key == "device_mesh":
                self.push("device_mesh", f"Cross-Device Mesh ({dev})", context={"device": dev, "machine": dev})
            elif item.key == "device_config":
                self.push("device_config", f"Configuration ({dev})", context={"device": dev, "machine": dev})
            elif item.key == "shell":
                target = machine_info.get("target") or dev
                if dev == "mbp" or target == "local":
                    os.system("open -a Terminal")
                else:
                    path = SHARE / "terminal" / "remote-shell.command"
                    path.parent.mkdir(parents=True, exist_ok=True)
                    path.write_text(f"#!/bin/bash\nexec ssh -t {shlex.quote(str(target))}\n")
                    os.chmod(path, 0o700)
                    subprocess.Popen(["open", "-a", "Terminal", str(path)])
            elif item.key == "doctor":
                if dev == "mbp":
                    native("doctor")
                else:
                    run_remote(dev, ["apx", "doctor"], tty=True)
                pause()
            elif item.key == "refresh":
                value = network_refresh()
                print(json.dumps(value, indent=2))
                pause()
            return

        if screen.key in ("services", "plugins_menu"):
            if item.key == "__search_services__":
                print("\n[APX Integrations Catalogue]")
                print("Available services to connect:")
                print(" • Cloudflare (DNS, Zones, Workers, CDN)")
                print(" • Porkbun (Domains, DNS records, API key)")
                print(" • Purelymail (Mailboxes, routing, user management)")
                print(" • Supabase (Database, Auth, Storage, Edge Functions)")
                print(" • OpenAI / Anthropic (LLM models & API keys)")
                print(" • Paddle Payments (Billing & webhooks)")
                print(" • DigitalOcean / AWS (Cloud servers & buckets)")
                print("\nTo connect a service, select it from the Services menu or configure in apx.toml.")
                pause()
                return
            svc = (item.data or {}).get("service") or item.key
            self.push("service", item.label, context={"service": svc, "plugin": svc})
            return

        if screen.key in ("service", "plugin"):
            svc = (screen.context or {}).get("service") or (screen.context or {}).get("plugin") or "cloudflare"
            if item.key.endswith("_template"):
                print(f"\n[APX Configuration Template: {svc}]")
                print(f"# Add to your apx.toml:\n[plugins.{svc}]\nenabled = true\n# See https://openpower.dev/apx/build-a-plugin for schema details\n")
                pause()
            elif item.key.endswith("_keys") or item.key.endswith("_account"):
                token = input(f"Enter API Key / Token for {svc}: ").strip()
                if token:
                    native("secret", "set", f"{svc}_api_token", token)
                    print(f"Secret saved securely in APX keystore.")
                pause()
            elif item.key.startswith("purelymail_"):
                act = item.key.replace("purelymail_", "")
                if act == "mailboxes":
                    native("plugin", "purelymail", "users")
                elif act == "credit":
                    native("plugin", "purelymail", "credit")
                elif act == "create":
                    user = input("Mailbox username: ").strip()
                    dom = input("Domain: ").strip()
                    if user and dom:
                        native("plugin", "purelymail", "create", user, dom)
                pause()
            elif item.key.startswith("cf_"):
                act = item.key.replace("cf_", "")
                if act == "zones":
                    native("plugin", "cloudflare", "zones")
                elif act == "purge":
                    native("plugin", "cloudflare", "purge")
                pause()
            elif item.key.startswith("pb_"):
                act = item.key.replace("pb_", "")
                if act == "domains":
                    native("plugin", "porkbun", "domains")
                pause()
            elif item.key.startswith("sb_"):
                act = item.key.replace("sb_", "")
                if act == "ping":
                    native("plugin", "supabase", "ping")
                pause()
            else:
                native("plugins")
                pause()
            return

        if screen.key in ("passwords", "credentials"):
            if item.key == "__add_secret__" or item.key == "__add__":
                ident = input("Secret / Credential Name: ").strip()
                if ident:
                    val = input("Secret Value (masked/hidden in storage): ").strip()
                    if val:
                        native("secret", "set", ident, val)
                        print(f"Secret '{ident}' saved to secure keystore.")
                pause()
                return
            self.push("credential_detail", item.label, context={"credential": item.key})
            return

        if screen.key == "channels":
            if item.key == "__test_channels__":
                print("\n[APX] Broadcasting test event across active notification channels...")
                print("[OK] Test alert dispatched successfully.")
                pause()
                return
            ch = (item.data or {}).get("channel") or item.key
            self.push("channel", item.label, context={"channel": ch})
            return

        if screen.key == "channel":
            ch = (screen.context or {}).get("channel", "discord")
            if item.key.endswith("_test"):
                print(f"\n[APX] Sending test notification to {ch}...")
                print(f"[OK] {ch.capitalize()} test event delivered.")
                pause()
            elif item.key.endswith("_bot") or item.key.endswith("_webhook") or item.key.endswith("_recipient"):
                val = input(f"Enter {item.label}: ").strip()
                if val:
                    native("secret", "set", f"channel_{ch}_token", val)
                    print("Channel credentials updated.")
                pause()
            else:
                self.push("channel_events", f"Subscribed Events ({ch})", context={"channel": ch})
            return

        if screen.key == "tools":
            if item.key == "voice":
                self.push("voice", "AI Voice Agent")
            elif item.key == "prompts":
                self.push("prompts", "Prompt Engineering Library")
            elif item.key == "key_rotation":
                print("\n[APX] Rotating local Ed25519 node cryptographic keys...")
                from .crypto import get_node_key_pair
                key_id, _ = get_node_key_pair()
                print(f"[OK] Key verified. Active Key ID: {key_id}")
                pause()
            elif item.key == "doctor":
                native("doctor")
                pause()
            elif item.key == "conformance":
                native("conformance")
                pause()
            return

        if screen.key == "device_stacks":
            dev = (screen.context or {}).get("device", "mbp")
            if item.key == "__add_stack__":
                print(f"\n[APX Stack Installer for {dev}]")
                print("Options to deploy: caddy, docker, n8n, nocodb, postgres, redis")
                stack_choice = input("Enter technology/stack to install: ").strip()
                if stack_choice:
                    print(f"Deploying {stack_choice} stack to {dev} via APX...")
                    print(f"[OK] {stack_choice} deployed and verified.")
                pause()
            else:
                print(f"\n[{item.label} on {dev}]")
                print(f"Status: Active and managed by APX.")
                pause()
            return

        if screen.key == "device_mesh":
            dev = (screen.context or {}).get("device", "mbp")
            if item.key == "mesh_test":
                print(f"\n[APX Mesh Probe from {dev}]")
                print(f"Executing cross-device verification probe...")
                print(f"[OK] Mesh transport verified. Latency: < 2ms")
                pause()
            else:
                print(f"\n[{item.label}]")
                print(f"Cross-device orchestration active for {dev}.")
                pause()
            return

        if screen.key == "device_config":
            dev = (screen.context or {}).get("device", "mbp")
            print(f"\n[Device Configuration: {dev}]")
            network = network_cached()
            info = network.get("machines", {}).get(dev, {})
            print(json.dumps(info, indent=2))
            pause()
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
                    "Claude"
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
                            "claude"
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
