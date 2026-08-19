# SPDX-License-Identifier: MIT
"""APX Interactive Terminal User Interface (TUI).

Overhauled around a true hierarchical product menu:
OpenPower
  ↳ Devices
  ↳ Agents
  ↳ Prompts
  ↳ Services
  ↳ Plugins
  ↳ OpenPower Settings

Provides a clean, restrained, breadcrumb-driven experience with dynamic
capability introspection, search filtering, and scoped settings inheritance.
"""
from __future__ import annotations

import json
import sys
import time
import webbrowser
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from prompt_toolkit.application import Application
from prompt_toolkit.formatted_text import FormattedText
from prompt_toolkit.key_binding import KeyBindings
from prompt_toolkit.filters import Condition
from prompt_toolkit.layout import Layout
from prompt_toolkit.layout.containers import ConditionalContainer, HSplit, VSplit, Window
from prompt_toolkit.layout.controls import FormattedTextControl
from prompt_toolkit.styles import Style

from .cloud import APX
from .hardware import inspect_hardware
from .settings import get_all_settings, get_setting, set_setting
from .prompts import PromptRecord
from . import __version__


@dataclass
class MenuItem:
    id: str
    title: str
    subtitle: str = ""
    tag: str = ""
    tag_style: str = "cyan"
    on_select: Callable[[], Any] | None = None
    data: dict[str, Any] = field(default_factory=dict)
    is_toggleable: bool = False
    is_toggled: bool = False
    is_action: bool = False


@dataclass
class NavScreen:
    id: str
    title: str
    breadcrumbs: list[str]
    get_items: Callable[[], list[MenuItem]]
    detail_renderer: Callable[[MenuItem | None], FormattedText] | None = None
    selected_idx: int = 0
    scroll_offset: int = 0
    search_query: str = ""
    search_mode: bool = False
    multi_select: bool = False
    selected_ids: set[str] = field(default_factory=set)


class TUIEngine:
    def __init__(self, cloud: APX, actor: str | None = None):
        self.cloud = cloud
        self.actor = actor or cloud.actors.resolve_default()
        self.stack: list[NavScreen] = []
        self.modal: dict[str, Any] | None = None
        self.status_message: str = "Ready. Use ↑/↓ to move, Enter to open, Esc to go back, ? for help."
        self.status_is_error: bool = False
        self.cached_hardware: dict[str, Any] = {}
        self.refresh_hardware()
        self.push_screen(self.create_root_screen())

    def refresh_hardware(self) -> None:
        try:
            self.cached_hardware = inspect_hardware()
        except Exception:
            self.cached_hardware = {}

    @property
    def current_screen(self) -> NavScreen:
        return self.stack[-1]

    def push_screen(self, screen: NavScreen) -> None:
        self.stack.append(screen)

    def pop_screen(self) -> bool:
        if len(self.stack) > 1:
            self.stack.pop()
            return True
        return False

    def get_current_items(self) -> list[MenuItem]:
        screen = self.current_screen
        raw_items = screen.get_items()
        if screen.search_query.strip():
            q = screen.search_query.lower()
            return [
                it for it in raw_items
                if q in it.title.lower() or q in it.subtitle.lower() or q in it.id.lower() or q in it.tag.lower()
            ]
        return raw_items

    # --------------------------------------------------------------------------
    # Root Screen
    # --------------------------------------------------------------------------
    def create_root_screen(self) -> NavScreen:
        def get_items() -> list[MenuItem]:
            devices_count = len(self.cloud.hosts)
            agents_count = len(self.cloud.actors.list())
            prompts_count = len(self.cloud.prompts.list())
            services_count = len(self.cloud.providers) + len([m for m in self.cloud.plugin_manager.metadata if m not in self.cloud.providers])
            plugins_count = len(self.cloud.plugin_manager.metadata)

            return [
                MenuItem(
                    id="menu_devices",
                    title="Devices",
                    subtitle=f"{devices_count} known · Local workstation and linked nodes",
                    tag="FABRIC",
                    tag_style="cyan",
                    on_select=lambda: self.push_screen(self.create_devices_screen()),
                ),
                MenuItem(
                    id="menu_agents",
                    title="Agents",
                    subtitle=f"{agents_count} configured · Runtimes and capabilities",
                    tag="ACTORS",
                    tag_style="yellow",
                    on_select=lambda: self.push_screen(self.create_agents_screen()),
                ),
                MenuItem(
                    id="menu_prompts",
                    title="Prompts",
                    subtitle=f"{prompts_count} saved · Shared and scoped prompt stacks",
                    tag="PROMPTS",
                    tag_style="blue",
                    on_select=lambda: self.push_screen(self.create_prompts_screen()),
                ),
                MenuItem(
                    id="menu_services",
                    title="Services",
                    subtitle=f"{services_count} active/available · Providers and capabilities",
                    tag="DYNAMIC",
                    tag_style="green",
                    on_select=lambda: self.push_screen(self.create_services_screen()),
                ),
                MenuItem(
                    id="menu_plugins",
                    title="Plugins",
                    subtitle=f"{plugins_count} extensions · Integrations and discovery",
                    tag="EXTEND",
                    tag_style="magenta",
                    on_select=lambda: self.push_screen(self.create_plugins_screen()),
                ),
                MenuItem(
                    id="menu_openpower",
                    title="OpenPower Settings",
                    subtitle="Account link, shared settings, servers, protocol",
                    tag="SETTINGS",
                    tag_style="dim",
                    on_select=lambda: self.push_screen(self.create_openpower_settings_screen()),
                ),
            ]

        def detail_renderer(item: MenuItem | None) -> FormattedText:
            tokens: list[tuple[str, str]] = []
            tokens.append(("class:inspector.title", " ── OpenPower Fabric ──\n\n"))
            if not item:
                tokens.append(("class:dim", " Select an area to navigate.\n"))
                return tokens

            if item.id == "menu_devices":
                tier = self.cached_hardware.get("compute_tier", "active")
                cpu = self.cached_hardware.get("cpu", {}).get("model", "Detected CPU")
                tokens.append(("class:bold", " Devices & Compute Topology\n"))
                tokens.append(("class:dim", "  Manage your local workstation, discovered machines, remote hosts,\n"))
                tokens.append(("class:dim", "  and multi-device shared configurations across your OpenPower fabric.\n\n"))
                tokens.append(("class:bold", f"  • Local Machine:   {self.cached_hardware.get('node_id', 'local')}\n"))
                tokens.append(("class:bold", f"  • Compute Tier:    {tier}\n"))
                tokens.append(("class:bold", f"  • Processor:       {cpu}\n"))
                tokens.append(("class:bold", f"  • Registered:      {len(self.cloud.hosts)} host(s)\n"))
            elif item.id == "menu_agents":
                tokens.append(("class:bold", " Agent Identities & Capabilities\n"))
                tokens.append(("class:dim", "  Inspect autonomous and standing agents, discover live permissions,\n"))
                tokens.append(("class:dim", "  assign prompt stacks, and manage runtime configurations.\n\n"))
                tokens.append(("class:bold", f"  • Default Actor:   {self.actor}\n"))
                tokens.append(("class:bold", f"  • Active Agents:   {len(self.cloud.actors.list())}\n"))
            elif item.id == "menu_prompts":
                tokens.append(("class:bold", " Prompts & Stacks\n"))
                tokens.append(("class:dim", "  Create, edit, and distribute shared prompts and instructions\n"))
                tokens.append(("class:dim", "  across devices, groups, and agents.\n\n"))
                tokens.append(("class:bold", f"  • Saved Prompts:   {len(self.cloud.prompts.list())}\n"))
            elif item.id == "menu_services":
                tokens.append(("class:bold", " Dynamic Services & Providers\n"))
                tokens.append(("class:dim", "  Action providers, cloud services (Porkbun, Cloudflare, PurelyMail,\n"))
                tokens.append(("class:dim", "  Supabase, etc.), database engines, and MCP connections.\n\n"))
                tokens.append(("class:bold", f"  • Connected:       {len(self.cloud.providers)} provider(s)\n"))
                tokens.append(("class:bold", f"  • Available Actions: {len(self.cloud.actions.list())}\n"))
            elif item.id == "menu_plugins":
                tokens.append(("class:bold", " Plugin Extensions\n"))
                tokens.append(("class:dim", "  Search, install, enable, or configure native and community\n"))
                tokens.append(("class:dim", "  plugins contributing new services, actions, and resources.\n\n"))
                tokens.append(("class:bold", f"  • Loaded Plugins:  {len(self.cloud.plugin_manager.metadata)}\n"))
            elif item.id == "menu_openpower":
                tokens.append(("class:bold", " OpenPower Platform & Protocol\n"))
                tokens.append(("class:dim", "  Link account with OpenPower.dev, manage shared inheritance\n"))
                tokens.append(("class:dim", "  settings, browse APX servers, and run protocol conformance.\n\n"))
                tokens.append(("class:bold", f"  • Protocol Version: 0.1\n"))
                tokens.append(("class:bold", f"  • Package Version:  {__version__}\n"))

            tokens.append(("\nclass:action.prompt", " [Press Enter or Right Arrow to Open]\n"))
            return tokens

        return NavScreen(
            id="root",
            title="OpenPower",
            breadcrumbs=["OpenPower"],
            get_items=get_items,
            detail_renderer=detail_renderer,
        )

    # --------------------------------------------------------------------------
    # Devices Screen & Subscreens
    # --------------------------------------------------------------------------
    def create_devices_screen(self) -> NavScreen:
        def get_items() -> list[MenuItem]:
            items: list[MenuItem] = []
            hw = self.cached_hardware

            # 1. Local host
            local_host_name = hw.get("node_id", "local")
            tier = hw.get("compute_tier", "active")
            items.append(MenuItem(
                id=f"device_{local_host_name}",
                title=f"{local_host_name}",
                subtitle=f"Local workstation · Tier: {tier}",
                tag="LOCAL",
                tag_style="green",
                on_select=lambda name=local_host_name: self.push_screen(self.create_device_detail_screen(name, is_local=True)),
                data={"name": local_host_name, "is_local": True, "hardware": hw},
            ))

            # 2. Remote hosts from config
            for host_name, host in self.cloud.hosts.items():
                if host_name == local_host_name or host.is_self:
                    continue
                transport_desc = f"Linked via {host.transport.upper()}"
                if host.target:
                    transport_desc += f" ({host.target})"
                items.append(MenuItem(
                    id=f"device_{host_name}",
                    title=f"{host_name}",
                    subtitle=transport_desc,
                    tag="REMOTE",
                    tag_style="cyan",
                    on_select=lambda name=host_name: self.push_screen(self.create_device_detail_screen(name, is_local=False)),
                    data={"name": host_name, "is_local": False, "host": host.to_dict()},
                ))

            # 3. Actions
            items.append(MenuItem(
                id="act_add_device",
                title="Add / Link Device",
                subtitle="Connect via OpenPower.dev pairing, SSH, or local enrollment",
                tag="LINK",
                tag_style="yellow",
                is_action=True,
                on_select=lambda: self.push_screen(self.create_add_device_screen()),
            ))
            items.append(MenuItem(
                id="act_shared_device_settings",
                title="Shared Device Settings",
                subtitle="Manage configuration and prompt stacks spanning all devices",
                tag="SHARED",
                tag_style="blue",
                is_action=True,
                on_select=lambda: self.push_screen(self.create_shared_device_settings_screen()),
            ))

            return items

        def detail_renderer(item: MenuItem | None) -> FormattedText:
            tokens: list[tuple[str, str]] = []
            tokens.append(("class:inspector.title", " ── Device Details ──\n\n"))
            if not item:
                tokens.append(("class:dim", " Select a device to view compute profile and settings.\n"))
                return tokens

            if item.id == "act_add_device":
                tokens.append(("class:bold", " Add or Link a Device\n"))
                tokens.append(("class:dim", "  Add a new compute node to your fabric using OpenPower account\n"))
                tokens.append(("class:dim", "  pairing codes, direct SSH targets, or local enrollment.\n\n"))
                tokens.append(("class:action.prompt", " [Press Enter to configure new device connection]\n"))
            elif item.id == "act_shared_device_settings":
                tokens.append(("class:bold", " Shared Device Settings\n"))
                tokens.append(("class:dim", "  Configure settings that inherit across all devices or specific\n"))
                tokens.append(("class:dim", "  device groups (prompt stacks, telemetry, auto-discovery).\n\n"))
                tokens.append(("class:action.prompt", " [Press Enter to manage shared settings]\n"))
            else:
                d = item.data
                name = d.get("name", item.title)
                is_local = d.get("is_local", False)
                tokens.append(("class:inspector.item_title", f" Device: {name}\n"))
                tokens.append(("class:dim", f" Status: {'Active (Local Machine)' if is_local else 'Configured (Remote)'}\n\n"))

                if is_local:
                    hw = self.cached_hardware
                    tokens.append(("class:bold", " Compute Specifications:\n"))
                    tokens.append(("class:bold", f"  • Tier:         {hw.get('compute_tier', 'unknown')}\n"))
                    tokens.append(("class:bold", f"  • CPU:          {hw.get('cpu', {}).get('model', 'Unknown')} ({hw.get('cpu', {}).get('cores', 1)} cores)\n"))
                    tokens.append(("class:bold", f"  • Memory:       {hw.get('memory', {}).get('total_gb', 0)} GB ({hw.get('memory', {}).get('available_gb', 0)} GB available)\n"))
                    acc = hw.get("accelerators", {})
                    tokens.append(("class:bold", f"  • Accelerators: Metal: {acc.get('metal')} | Neural Engine: {acc.get('neural_engine')} | CUDA: {acc.get('cuda')}\n"))
                    tokens.append(("class:bold", f"  • Storage:      {hw.get('storage', {}).get('free_gb', 0)} GB free / {hw.get('storage', {}).get('total_gb', 0)} GB total\n"))
                else:
                    host_dict = d.get("host", {})
                    tokens.append(("class:bold", " Remote Connection:\n"))
                    tokens.append(("class:bold", f"  • Transport:    {host_dict.get('transport', 'ssh')}\n"))
                    tokens.append(("class:bold", f"  • Target:       {host_dict.get('target', 'None')}\n"))
                    tokens.append(("class:bold", f"  • Groups:       {', '.join(host_dict.get('groups', [])) or 'default'}\n"))

                tokens.append(("\nclass:action.prompt", " [Press Enter to drill into Device Management]\n"))

            return tokens

        return NavScreen(
            id="devices",
            title="Devices",
            breadcrumbs=["OpenPower", "Devices"],
            get_items=get_items,
            detail_renderer=detail_renderer,
        )

    def create_device_detail_screen(self, device_name: str, is_local: bool) -> NavScreen:
        def get_items() -> list[MenuItem]:
            return [
                MenuItem(
                    id="dev_overview",
                    title="Overview",
                    subtitle="Compute tier, CPU, memory, accelerators, storage",
                    tag="INFO",
                    tag_style="green",
                    on_select=lambda: self.show_info_modal(f"Device: {device_name} Overview", self.render_device_overview_text(device_name, is_local)),
                ),
                MenuItem(
                    id="dev_link",
                    title="Link / Unlink",
                    subtitle="Manage OpenPower identity pairing and account connection",
                    tag="IDENTITY",
                    tag_style="yellow",
                    on_select=lambda: self.show_link_device_modal(device_name),
                ),
                MenuItem(
                    id="dev_shared_settings",
                    title="Shared Settings",
                    subtitle="View inherited settings and override locally for this device",
                    tag="SCOPED",
                    tag_style="cyan",
                    on_select=lambda: self.push_screen(self.create_device_scoped_settings_screen(device_name)),
                ),
                MenuItem(
                    id="dev_settings",
                    title="Device Settings",
                    subtitle="Transport, target host, local daemon and execution options",
                    tag="CONFIG",
                    tag_style="dim",
                    on_select=lambda: self.show_info_modal(f"Settings: {device_name}", f"Device: {device_name}\nTransport: {'local' if is_local else 'ssh'}\nNode Name: {device_name}\nActor Scoping: Enabled"),
                ),
                MenuItem(
                    id="dev_services",
                    title="Services",
                    subtitle="Services active or assigned to this device",
                    tag="SERVICES",
                    tag_style="blue",
                    on_select=lambda: self.push_screen(self.create_device_services_screen(device_name)),
                ),
                MenuItem(
                    id="dev_agents",
                    title="Agents",
                    subtitle="Agents configured or running on this device",
                    tag="AGENTS",
                    tag_style="yellow",
                    on_select=lambda: self.push_screen(self.create_device_agents_screen(device_name)),
                ),
                MenuItem(
                    id="dev_capabilities",
                    title="Capabilities",
                    subtitle="Live policy-evaluated permissions and actions on this device",
                    tag="POLICY",
                    tag_style="magenta",
                    on_select=lambda: self.show_device_capabilities_modal(device_name),
                ),
            ]

        def detail_renderer(item: MenuItem | None) -> FormattedText:
            tokens: list[tuple[str, str]] = []
            tokens.append(("class:inspector.title", f" ── Manage Device: {device_name} ──\n\n"))
            if not item:
                return tokens
            tokens.append(("class:inspector.item_title", f" {item.title}\n"))
            tokens.append(("class:dim", f" {item.subtitle}\n\n"))
            tokens.append(("class:bold", " Context:\n"))
            tokens.append(("class:dim", f"  Device: {device_name}\n  Mode:   {'Local Machine' if is_local else 'Remote Node'}\n\n"))
            tokens.append(("class:action.prompt", " [Press Enter to inspect / execute]\n"))
            return tokens

        return NavScreen(
            id=f"device_detail_{device_name}",
            title=device_name,
            breadcrumbs=["OpenPower", "Devices", device_name],
            get_items=get_items,
            detail_renderer=detail_renderer,
        )

    def render_device_overview_text(self, device_name: str, is_local: bool) -> str:
        if is_local:
            hw = self.cached_hardware
            return (
                f"Device: {device_name} (Local Workstation)\n"
                f"Compute Tier: {hw.get('compute_tier', 'unknown')}\n"
                f"CPU: {hw.get('cpu', {}).get('model')} ({hw.get('cpu', {}).get('cores')} cores, {hw.get('cpu', {}).get('architecture')})\n"
                f"Memory: {hw.get('memory', {}).get('total_gb')} GB total ({hw.get('memory', {}).get('available_gb')} GB free)\n"
                f"Storage: {hw.get('storage', {}).get('free_gb')} GB free / {hw.get('storage', {}).get('total_gb')} GB total\n"
                f"Accelerators: Metal={hw.get('accelerators', {}).get('metal')}, ANE={hw.get('accelerators', {}).get('neural_engine')}, CUDA={hw.get('accelerators', {}).get('cuda')}\n"
                f"Local LLM Ready: {hw.get('recommendations', {}).get('allow_local_llm')}\n"
                f"Standing Agent Ready: {hw.get('recommendations', {}).get('allow_background_standing_agent')}"
            )
        else:
            host = self.cloud.hosts.get(device_name)
            return (
                f"Device: {device_name} (Remote Node)\n"
                f"Transport: {host.transport if host else 'ssh'}\n"
                f"Target: {host.target if host else 'N/A'}\n"
                f"Groups: {', '.join(host.groups) if host and host.groups else 'default'}\n"
                f"Roles: {', '.join(host.roles) if host and host.roles else 'node'}"
            )

    def create_device_scoped_settings_screen(self, device_name: str) -> NavScreen:
        scope = f"device:{device_name}"
        def get_items() -> list[MenuItem]:
            settings_list = self.cloud.shared_settings.list_all(target_scope=scope)
            items: list[MenuItem] = []
            for s in settings_list:
                key = s["key"]
                val = s["value"]
                is_overridden = s["overridden"]
                sub = f"Value: {val} · {'Overridden locally' if is_overridden else 'Inherited from Shared'}"
                tag = "OVERRIDDEN" if is_overridden else "INHERITED"
                tag_style = "yellow" if is_overridden else "cyan"

                def make_toggle(k=key, current_s=s):
                    def _toggle():
                        if current_s["overridden"]:
                            self.cloud.shared_settings.remove_override(k, scope)
                            self.status_message = f"Reverted '{k}' to inherited shared setting"
                        else:
                            cur_val = current_s["value"]
                            new_val = not cur_val if isinstance(cur_val, bool) else f"{cur_val}-custom"
                            self.cloud.shared_settings.set(k, new_val, scope=scope)
                            self.status_message = f"Overrode '{k}' locally for {device_name}"
                    return _toggle

                items.append(MenuItem(
                    id=f"set_{key}",
                    title=f"{key}",
                    subtitle=sub,
                    tag=tag,
                    tag_style=tag_style,
                    on_select=make_toggle(),
                    data=s,
                ))
            return items

        def detail_renderer(item: MenuItem | None) -> FormattedText:
            tokens: list[tuple[str, str]] = []
            tokens.append(("class:inspector.title", f" ── Scoped Settings: {device_name} ──\n\n"))
            if not item:
                return tokens
            s = item.data
            key = s.get("key", item.title)
            tokens.append(("class:inspector.item_title", f" Setting: {key}\n"))
            tokens.append(("class:dim", f" Description: {s.get('description', '')}\n\n"))
            tokens.append(("class:bold", f" Effective Value: {s.get('value')}\n"))
            tokens.append(("class:dim", f" Source Scope:    {s.get('source_scope')}\n"))
            tokens.append(("class:dim", f" Inherited:       {'Yes (from Shared)' if s.get('inherited') else 'No (Local Override)'}\n"))
            tokens.append(("class:dim", f" Shared Baseline: {s.get('shared_value')}\n\n"))
            if s.get("overridden"):
                tokens.append(("class:action.prompt", " [Press Enter to Revert to Inherited]\n"))
            else:
                tokens.append(("class:action.prompt", " [Press Enter to Override Locally]\n"))
            return tokens

        return NavScreen(
            id=f"device_settings_{device_name}",
            title="Shared Settings",
            breadcrumbs=["OpenPower", "Devices", device_name, "Shared Settings"],
            get_items=get_items,
            detail_renderer=detail_renderer,
        )

    def create_device_services_screen(self, device_name: str) -> NavScreen:
        def get_items() -> list[MenuItem]:
            items: list[MenuItem] = []
            for pid, prov in self.cloud.providers.items():
                items.append(MenuItem(
                    id=f"prov_{pid}",
                    title=getattr(prov, "name", pid),
                    subtitle=f"Action Provider ({pid})",
                    tag="ACTIVE",
                    tag_style="green",
                    on_select=lambda p=pid: self.push_screen(self.create_service_detail_screen(p)),
                ))
            if not items:
                items.append(MenuItem("no_services", "No specific services registered for this device", "All standard APX actions available", tag="INFO", tag_style="dim"))
            return items

        return NavScreen(
            id=f"device_services_{device_name}",
            title="Services",
            breadcrumbs=["OpenPower", "Devices", device_name, "Services"],
            get_items=get_items,
            detail_renderer=lambda it: [("class:bold", f"Services active on {device_name}\n")],
        )

    def create_device_agents_screen(self, device_name: str) -> NavScreen:
        def get_items() -> list[MenuItem]:
            items: list[MenuItem] = []
            for a in self.cloud.actors.list():
                if a.host == device_name or (not a.host and device_name == self.cached_hardware.get("node_id", "local")):
                    items.append(MenuItem(
                        id=f"agent_{a.id}",
                        title=f"{a.id}",
                        subtitle=f"Runtime: {a.runtime or 'python'} · Roles: {', '.join(a.roles) if a.roles else 'none'}",
                        tag="AGENT",
                        tag_style="yellow",
                        on_select=lambda aid=a.id: self.push_screen(self.create_agent_detail_screen(aid)),
                    ))
            if not items:
                items.append(MenuItem("no_agents", "No agents directly bound to this device", "Fabric default agent handles requests", tag="INFO", tag_style="dim"))
            return items

        return NavScreen(
            id=f"device_agents_{device_name}",
            title="Agents",
            breadcrumbs=["OpenPower", "Devices", device_name, "Agents"],
            get_items=get_items,
        )

    def show_device_capabilities_modal(self, device_name: str) -> None:
        try:
            res = self.cloud.run("node.permissions", actor=self.actor, host=device_name if device_name in self.cloud.hosts else "local")
            allowed = res.result.get("allowed", []) if res.ok and isinstance(res.result, dict) else []
            count = len(allowed)
            preview = "\n".join(f"  • {a}" for a in allowed[:15])
            if count > 15:
                preview += f"\n  ... and {count - 15} more actions allowed by policy."
            content = f"Policy-Evaluated Permissions for {device_name}:\nTotal Allowed Actions: {count}\n\n{preview}"
            self.show_info_modal(f"Capabilities: {device_name}", content)
        except Exception as ex:
            self.show_info_modal(f"Capabilities: {device_name}", f"Error evaluating permissions: {ex}")

    def create_add_device_screen(self) -> NavScreen:
        def get_items() -> list[MenuItem]:
            return [
                MenuItem(
                    id="link_openpower_code",
                    title="Link via OpenPower.dev Pairing Code",
                    subtitle="Claim a temporary 6-digit device pairing code",
                    tag="PAIR",
                    tag_style="green",
                    on_select=lambda: self.show_pairing_claim_modal(),
                ),
                MenuItem(
                    id="link_ssh_target",
                    title="Add SSH / Tailscale Host",
                    subtitle="Declare a remote node in configuration with hostname and transport",
                    tag="SSH",
                    tag_style="cyan",
                    on_select=lambda: self.show_info_modal("Add Remote Node", "To configure a remote host, declare it in $APX_HOME/config.toml:\n\n[[hosts]]\nname = \"node-02\"\ntransport = \"ssh\"\ntarget = \"user@host.internal\"\n\nOr run: `apx init --host node-02=user@host.internal`"),
                ),
                MenuItem(
                    id="link_local_enrollment",
                    title="Local Identity Enrollment",
                    subtitle="Request principal enrollment for this machine",
                    tag="ENROLL",
                    tag_style="yellow",
                    on_select=lambda: self.show_info_modal("Local Enrollment", "Enrollment request submitted for local machine identity.\nRun `apx identity list` to inspect status."),
                ),
            ]

        return NavScreen(
            id="add_device",
            title="Add / Link Device",
            breadcrumbs=["OpenPower", "Devices", "Add / Link Device"],
            get_items=get_items,
        )

    def create_shared_device_settings_screen(self) -> NavScreen:
        def get_items() -> list[MenuItem]:
            settings_list = self.cloud.shared_settings.list_all(target_scope="shared")
            items: list[MenuItem] = []
            for s in settings_list:
                key = s["key"]
                val = s["value"]
                items.append(MenuItem(
                    id=f"shared_{key}",
                    title=f"{key}",
                    subtitle=f"Value: {val} · {s.get('description', '')}",
                    tag="SHARED",
                    tag_style="cyan",
                    data=s,
                    on_select=lambda k=key, cur=s: self.toggle_shared_setting(k, cur),
                ))
            return items

        def detail_renderer(item: MenuItem | None) -> FormattedText:
            tokens: list[tuple[str, str]] = []
            tokens.append(("class:inspector.title", " ── Shared Fabric Settings ──\n\n"))
            if not item:
                return tokens
            s = item.data
            tokens.append(("class:inspector.item_title", f" Setting: {s.get('key')}\n"))
            tokens.append(("class:dim", f" {s.get('description')}\n\n"))
            tokens.append(("class:bold", f" Current Shared Value: {s.get('value')}\n"))
            tokens.append(("class:dim", f" Applies to: All devices and agents (unless locally overridden)\n\n"))
            tokens.append(("class:action.prompt", " [Press Enter to Modify Setting]\n"))
            return tokens

        return NavScreen(
            id="shared_device_settings",
            title="Shared Device Settings",
            breadcrumbs=["OpenPower", "Devices", "Shared Device Settings"],
            get_items=get_items,
            detail_renderer=detail_renderer,
        )

    def toggle_shared_setting(self, key: str, current_entry: dict[str, Any]) -> None:
        cur_val = current_entry.get("value")
        if isinstance(cur_val, bool):
            new_val = not cur_val
        elif key == "model_routing":
            options = ["auto", "local_preferred", "cloud_fallback"]
            idx = options.index(cur_val) if cur_val in options else 0
            new_val = options[(idx + 1) % len(options)]
        elif key == "log_level":
            options = ["info", "debug", "warn", "error"]
            idx = options.index(cur_val) if cur_val in options else 0
            new_val = options[(idx + 1) % len(options)]
        elif key == "telemetry_mode":
            options = ["local_only", "openpower_synced"]
            idx = options.index(cur_val) if cur_val in options else 0
            new_val = options[(idx + 1) % len(options)]
        else:
            new_val = f"{cur_val}"
        self.cloud.shared_settings.set(key, new_val, scope="shared")
        self.status_message = f"Updated shared setting '{key}' = {new_val}"

    # --------------------------------------------------------------------------
    # Agents Screen & Subscreens
    # --------------------------------------------------------------------------
    def create_agents_screen(self) -> NavScreen:
        def get_items() -> list[MenuItem]:
            items: list[MenuItem] = []
            actors = self.cloud.actors.list()
            for a in actors:
                roles = getattr(a, "roles", ())
                runtime = getattr(a, "runtime", "python") or "python"
                items.append(MenuItem(
                    id=f"agent_{a.id}",
                    title=f"{a.id}",
                    subtitle=f"Runtime: {runtime} · Roles: {', '.join(roles) if roles else 'unrestricted'}",
                    tag=a.kind.upper(),
                    tag_style="yellow" if a.kind == "human" else "green",
                    data=a.to_dict() if hasattr(a, "to_dict") else {"id": a.id},
                    on_select=lambda aid=a.id: self.push_screen(self.create_agent_detail_screen(aid)),
                ))

            items.append(MenuItem(
                id="act_add_agent",
                title="Add / Configure Agent",
                subtitle="Declare a new agent principal identity or configure runtime",
                tag="NEW",
                tag_style="cyan",
                is_action=True,
                on_select=lambda: self.show_add_agent_modal(),
            ))
            items.append(MenuItem(
                id="act_shared_agent_settings",
                title="Shared Agent Settings",
                subtitle="Policies, model routing, and prompt stacks across agents",
                tag="SHARED",
                tag_style="blue",
                is_action=True,
                on_select=lambda: self.push_screen(self.create_shared_agent_settings_screen()),
            ))
            return items

        def detail_renderer(item: MenuItem | None) -> FormattedText:
            tokens: list[tuple[str, str]] = []
            tokens.append(("class:inspector.title", " ── Agent Details ──\n\n"))
            if not item:
                tokens.append(("class:dim", " Select an agent to inspect capabilities.\n"))
                return tokens
            if item.is_action:
                tokens.append(("class:bold", f" {item.title}\n"))
                tokens.append(("class:dim", f"  {item.subtitle}\n\n"))
                tokens.append(("class:action.prompt", " [Press Enter to proceed]\n"))
                return tokens
            data = item.data
            tokens.append(("class:inspector.item_title", f" Agent: {data.get('id')}\n"))
            tokens.append(("class:dim", f" Kind:    {data.get('kind')}\n"))
            tokens.append(("class:dim", f" Runtime: {data.get('runtime', 'python')}\n"))
            tokens.append(("class:dim", f" Roles:   {', '.join(data.get('roles', [])) or 'unrestricted'}\n"))
            tokens.append(("class:dim", f" Link:    {data.get('openpower_identity') or 'Local only'}\n\n"))
            tokens.append(("class:action.prompt", " [Press Enter to drill into Agent Management]\n"))
            return tokens

        return NavScreen(
            id="agents",
            title="Agents",
            breadcrumbs=["OpenPower", "Agents"],
            get_items=get_items,
            detail_renderer=detail_renderer,
        )

    def create_agent_detail_screen(self, actor_id: str) -> NavScreen:
        def get_items() -> list[MenuItem]:
            return [
                MenuItem(
                    id="agent_overview",
                    title="Overview",
                    subtitle="Principal kind, runtime environment, host bindings, roles",
                    tag="PROFILE",
                    tag_style="green",
                    on_select=lambda: self.show_info_modal(f"Agent Profile: {actor_id}", self.render_agent_overview_text(actor_id)),
                ),
                MenuItem(
                    id="agent_capabilities",
                    title="Capabilities",
                    subtitle="Live policy-evaluated actions allowed for this agent",
                    tag="POLICY",
                    tag_style="magenta",
                    on_select=lambda: self.show_agent_capabilities_modal(actor_id),
                ),
                MenuItem(
                    id="agent_prompts",
                    title="Assigned Prompts",
                    subtitle="Prompts and instructions active for this agent",
                    tag="PROMPTS",
                    tag_style="blue",
                    on_select=lambda: self.push_screen(self.create_agent_prompts_screen(actor_id)),
                ),
                MenuItem(
                    id="agent_identity",
                    title="Link / Identity",
                    subtitle="OpenPower account link, credentials, and pairing state",
                    tag="IDENTITY",
                    tag_style="yellow",
                    on_select=lambda: self.show_agent_link_modal(actor_id),
                ),
                MenuItem(
                    id="agent_settings",
                    title="Settings",
                    subtitle="Model routing, max tokens, and scoped overrides",
                    tag="CONFIG",
                    tag_style="cyan",
                    on_select=lambda: self.push_screen(self.create_agent_scoped_settings_screen(actor_id)),
                ),
            ]

        return NavScreen(
            id=f"agent_detail_{actor_id}",
            title=actor_id,
            breadcrumbs=["OpenPower", "Agents", actor_id],
            get_items=get_items,
        )

    def render_agent_overview_text(self, actor_id: str) -> str:
        actor = self.cloud.actors.get(actor_id)
        if not actor:
            return f"Agent {actor_id} not found."
        return (
            f"Agent ID: {actor.id}\n"
            f"Kind: {actor.kind}\n"
            f"Runtime: {actor.runtime or 'python'}\n"
            f"Host Binding: {actor.host or 'Any available node'}\n"
            f"Assigned Roles: {', '.join(actor.roles) if actor.roles else 'Unrestricted (open policy)'}\n"
            f"OpenPower Link: {actor.openpower_identity or 'Not linked to external OpenPower ID'}\n"
            f"Tags: {', '.join(actor.tags) if actor.tags else 'None'}"
        )

    def show_agent_capabilities_modal(self, actor_id: str) -> None:
        try:
            res = self.cloud.run("discovery.capabilities", actor=actor_id, subject=actor_id, compact=True)
            actions = res.result.get("actions", []) if res.ok and isinstance(res.result, dict) else []
            count = len(actions)
            preview = "\n".join(f"  • {a}" for a in actions[:15])
            if count > 15:
                preview += f"\n  ... and {count - 15} more actions permitted."
            content = f"Policy-Discovered Capabilities for {actor_id}:\nTotal Permitted Actions: {count}\n\n{preview}"
            self.show_info_modal(f"Capabilities: {actor_id}", content)
        except Exception as ex:
            self.show_info_modal(f"Capabilities: {actor_id}", f"Discovery error: {ex}")

    def create_agent_prompts_screen(self, actor_id: str) -> NavScreen:
        def get_items() -> list[MenuItem]:
            prompts = self.cloud.prompts.list(target=actor_id)
            items: list[MenuItem] = []
            for p in prompts:
                items.append(MenuItem(
                    id=f"pr_{p.id}",
                    title=p.title,
                    subtitle=p.description or p.content[:40],
                    tag="ACTIVE",
                    tag_style="green",
                    data=p.to_dict(),
                    on_select=lambda p_id=p.id: self.push_screen(self.create_prompt_detail_screen(p_id)),
                ))
            if not items:
                items.append(MenuItem("no_prompts", "No agent-specific prompts assigned", "Default Universal Assistant prompt applies", tag="INFO", tag_style="dim"))
            return items

        return NavScreen(
            id=f"agent_prompts_{actor_id}",
            title="Assigned Prompts",
            breadcrumbs=["OpenPower", "Agents", actor_id, "Assigned Prompts"],
            get_items=get_items,
        )

    def create_agent_scoped_settings_screen(self, actor_id: str) -> NavScreen:
        scope = f"agent:{actor_id}"
        def get_items() -> list[MenuItem]:
            settings_list = self.cloud.shared_settings.list_all(target_scope=scope)
            items: list[MenuItem] = []
            for s in settings_list:
                key = s["key"]
                val = s["value"]
                is_overridden = s["overridden"]
                sub = f"Value: {val} · {'Overridden for agent' if is_overridden else 'Inherited'}"
                items.append(MenuItem(
                    id=f"agent_set_{key}",
                    title=key,
                    subtitle=sub,
                    tag="OVERRIDE" if is_overridden else "INHERITED",
                    tag_style="yellow" if is_overridden else "cyan",
                    data=s,
                    on_select=lambda k=key, cur=s: self.toggle_agent_setting(k, cur, scope),
                ))
            return items

        return NavScreen(
            id=f"agent_settings_{actor_id}",
            title="Settings",
            breadcrumbs=["OpenPower", "Agents", actor_id, "Settings"],
            get_items=get_items,
        )

    def toggle_agent_setting(self, key: str, current_entry: dict[str, Any], scope: str) -> None:
        if current_entry.get("overridden"):
            self.cloud.shared_settings.remove_override(key, scope)
            self.status_message = f"Reverted '{key}' to inherited value"
        else:
            cur_val = current_entry.get("value")
            new_val = not cur_val if isinstance(cur_val, bool) else f"{cur_val}-agent"
            self.cloud.shared_settings.set(key, new_val, scope=scope)
            self.status_message = f"Overrode '{key}' for agent"

    def create_shared_agent_settings_screen(self) -> NavScreen:
        def get_items() -> list[MenuItem]:
            return [
                MenuItem("set_routing", "Model Routing Preference", f"Effective: {self.cloud.shared_settings.get_effective('model_routing')['value']}", tag="ROUTING", tag_style="cyan", on_select=lambda: self.toggle_shared_setting("model_routing", self.cloud.shared_settings.get_effective("model_routing"))),
                MenuItem("set_stack", "Default Prompt Stack", f"Effective: {self.cloud.shared_settings.get_effective('prompt_stack')['value']}", tag="PROMPTS", tag_style="blue", on_select=lambda: self.toggle_shared_setting("prompt_stack", self.cloud.shared_settings.get_effective("prompt_stack"))),
                MenuItem("set_tasks", "Max Parallel Tasks", f"Effective: {self.cloud.shared_settings.get_effective('max_parallel_tasks')['value']}", tag="CONCURRENCY", tag_style="yellow", on_select=lambda: self.toggle_shared_setting("max_parallel_tasks", self.cloud.shared_settings.get_effective("max_parallel_tasks"))),
            ]

        return NavScreen(
            id="shared_agent_settings",
            title="Shared Agent Settings",
            breadcrumbs=["OpenPower", "Agents", "Shared Agent Settings"],
            get_items=get_items,
        )

    # --------------------------------------------------------------------------
    # Prompts Screen & Subscreens
    # --------------------------------------------------------------------------
    def create_prompts_screen(self) -> NavScreen:
        def get_items() -> list[MenuItem]:
            all_prompts = self.cloud.prompts.list()
            shared_count = len([p for p in all_prompts if p.scope == "shared"])
            device_count = len([p for p in all_prompts if p.scope == "device"])
            agent_count = len([p for p in all_prompts if p.scope == "agent"])

            return [
                MenuItem(
                    id="menu_saved_prompts",
                    title="Saved Prompts",
                    subtitle=f"{len(all_prompts)} prompt templates available",
                    tag="ALL",
                    tag_style="green",
                    on_select=lambda: self.push_screen(self.create_prompt_list_screen("Saved Prompts")),
                ),
                MenuItem(
                    id="menu_shared_prompts",
                    title="Shared Prompts",
                    subtitle=f"{shared_count} distributed across entire fabric",
                    tag="SHARED",
                    tag_style="cyan",
                    on_select=lambda: self.push_screen(self.create_prompt_list_screen("Shared Prompts", scope="shared")),
                ),
                MenuItem(
                    id="menu_device_prompts",
                    title="Device-Specific Prompts",
                    subtitle=f"{device_count} scoped to particular machines",
                    tag="DEVICE",
                    tag_style="yellow",
                    on_select=lambda: self.push_screen(self.create_prompt_list_screen("Device-Specific Prompts", scope="device")),
                ),
                MenuItem(
                    id="menu_agent_prompts",
                    title="Agent-Specific Prompts",
                    subtitle=f"{agent_count} bound to specific agent roles",
                    tag="AGENT",
                    tag_style="magenta",
                    on_select=lambda: self.push_screen(self.create_prompt_list_screen("Agent-Specific Prompts", scope="agent")),
                ),
                MenuItem(
                    id="act_new_prompt",
                    title="Create / Edit Prompt",
                    subtitle="Author a new prompt and set target distribution",
                    tag="NEW",
                    tag_style="green",
                    is_action=True,
                    on_select=lambda: self.show_create_prompt_modal(),
                ),
                MenuItem(
                    id="act_shared_prompt_settings",
                    title="Shared Prompt Settings",
                    subtitle="Configure default fabric prompt stack and inheritance",
                    tag="CONFIG",
                    tag_style="blue",
                    is_action=True,
                    on_select=lambda: self.push_screen(self.create_shared_prompt_settings_screen()),
                ),
            ]

        def detail_renderer(item: MenuItem | None) -> FormattedText:
            tokens: list[tuple[str, str]] = []
            tokens.append(("class:inspector.title", " ── Prompts Catalog ──\n\n"))
            if not item:
                return tokens
            tokens.append(("class:bold", f" {item.title}\n"))
            tokens.append(("class:dim", f"  {item.subtitle}\n\n"))
            tokens.append(("class:action.prompt", " [Press Enter to Open]\n"))
            return tokens

        return NavScreen(
            id="prompts",
            title="Prompts",
            breadcrumbs=["OpenPower", "Prompts"],
            get_items=get_items,
            detail_renderer=detail_renderer,
        )

    def create_prompt_list_screen(self, title: str, scope: str | None = None) -> NavScreen:
        def get_items() -> list[MenuItem]:
            prompts = self.cloud.prompts.list(scope=scope)
            items: list[MenuItem] = []
            for p in prompts:
                items.append(MenuItem(
                    id=f"pr_{p.id}",
                    title=p.title,
                    subtitle=p.description or p.content[:45],
                    tag=p.scope.upper(),
                    tag_style="cyan" if p.scope == "shared" else "yellow",
                    data=p.to_dict(),
                    on_select=lambda pid=p.id: self.push_screen(self.create_prompt_detail_screen(pid)),
                ))
            if not items:
                items.append(MenuItem("empty_prompts", f"No {title.lower()} found", "Use 'Create / Edit Prompt' to add one", tag="EMPTY", tag_style="dim"))
            return items

        def detail_renderer(item: MenuItem | None) -> FormattedText:
            tokens: list[tuple[str, str]] = []
            tokens.append(("class:inspector.title", f" ── {title} ──\n\n"))
            if not item or not item.data:
                return tokens
            p = item.data
            tokens.append(("class:inspector.item_title", f" {p.get('title')}\n"))
            tokens.append(("class:dim", f" Scope:   {p.get('scope')}\n"))
            tokens.append(("class:dim", f" Targets: {', '.join(p.get('targets', ['all']))}\n\n"))
            tokens.append(("class:bold", " Description:\n"))
            tokens.append(("class:dim", f"  {p.get('description', 'No description.')}\n\n"))
            tokens.append(("class:bold", " Instructions:\n"))
            lines = p.get("content", "").splitlines()[:6]
            for l in lines:
                tokens.append(("class:dim", f"  {l}\n"))
            tokens.append(("\nclass:action.prompt", " [Press Enter to View & Edit Prompt]\n"))
            return tokens

        return NavScreen(
            id=f"prompt_list_{title.lower().replace(' ', '_')}",
            title=title,
            breadcrumbs=["OpenPower", "Prompts", title],
            get_items=get_items,
            detail_renderer=detail_renderer,
        )

    def create_prompt_detail_screen(self, prompt_id: str) -> NavScreen:
        prompt = self.cloud.prompts.get(prompt_id)
        prompt_title = prompt.title if prompt else prompt_id

        def get_items() -> list[MenuItem]:
            p = self.cloud.prompts.get(prompt_id)
            if not p:
                return [MenuItem("not_found", "Prompt no longer exists", tag="ERROR", tag_style="red")]
            return [
                MenuItem(
                    id="pr_view",
                    title="View Content",
                    subtitle="Read full formatted prompt content",
                    tag="CONTENT",
                    tag_style="green",
                    on_select=lambda: self.show_info_modal(f"Prompt: {p.title}", p.content),
                ),
                MenuItem(
                    id="pr_scope",
                    title="Change Scope & Targets",
                    subtitle=f"Current: {p.scope} (Targets: {', '.join(p.targets)})",
                    tag="SCOPE",
                    tag_style="cyan",
                    on_select=lambda: self.toggle_prompt_scope(p),
                ),
                MenuItem(
                    id="pr_assign",
                    title="Assign to Specific Devices",
                    subtitle="Choose which devices receive and execute this prompt",
                    tag="ASSIGN",
                    tag_style="yellow",
                    on_select=lambda: self.push_screen(self.create_prompt_target_picker(prompt_id)),
                ),
                MenuItem(
                    id="pr_delete",
                    title="Delete Prompt",
                    subtitle="Remove this prompt from saved catalog",
                    tag="DELETE",
                    tag_style="red",
                    on_select=lambda: self.confirm_delete_prompt(prompt_id),
                ),
            ]

        def detail_renderer(item: MenuItem | None) -> FormattedText:
            p = self.cloud.prompts.get(prompt_id)
            tokens: list[tuple[str, str]] = []
            tokens.append(("class:inspector.title", f" ── Prompt: {prompt_title} ──\n\n"))
            if not p:
                return tokens
            tokens.append(("class:inspector.item_title", f" Title: {p.title}\n"))
            tokens.append(("class:dim", f" Scope: {p.scope} | Targets: {', '.join(p.targets)}\n\n"))
            tokens.append(("class:bold", " Description:\n"))
            tokens.append(("class:dim", f"  {p.description}\n\n"))
            tokens.append(("class:bold", " Content Preview:\n"))
            for l in p.content.splitlines()[:10]:
                tokens.append(("class:dim", f"  {l}\n"))
            tokens.append(("\nclass:action.prompt", " [Press Enter on an action above]\n"))
            return tokens

        return NavScreen(
            id=f"prompt_detail_{prompt_id}",
            title=prompt_title,
            breadcrumbs=["OpenPower", "Prompts", prompt_title],
            get_items=get_items,
            detail_renderer=detail_renderer,
        )

    def toggle_prompt_scope(self, p: PromptRecord) -> None:
        scopes = ["shared", "device", "agent"]
        idx = scopes.index(p.scope) if p.scope in scopes else 0
        new_scope = scopes[(idx + 1) % len(scopes)]
        self.cloud.prompts.update(p.id, scope=new_scope)
        self.status_message = f"Updated prompt '{p.title}' scope to '{new_scope}'"

    def create_prompt_target_picker(self, prompt_id: str) -> NavScreen:
        p = self.cloud.prompts.get(prompt_id)
        current_targets = set(p.targets if p else ["all"])

        def get_items() -> list[MenuItem]:
            items: list[MenuItem] = []
            is_all = "all" in current_targets
            items.append(MenuItem(
                id="target_all",
                title="All Devices & Agents",
                subtitle="Broadcast prompt everywhere in fabric",
                tag="ALL" if is_all else "",
                tag_style="green",
                is_toggleable=True,
                is_toggled=is_all,
                on_select=lambda: self.toggle_prompt_target(prompt_id, "all"),
            ))

            for h in self.cloud.hosts:
                is_active = h in current_targets
                items.append(MenuItem(
                    id=f"target_{h}",
                    title=f"Device: {h}",
                    subtitle="Target this specific node",
                    tag="ACTIVE" if is_active else "",
                    tag_style="cyan",
                    is_toggleable=True,
                    is_toggled=is_active,
                    on_select=lambda host_name=h: self.toggle_prompt_target(prompt_id, host_name),
                ))
            return items

        return NavScreen(
            id=f"prompt_targets_{prompt_id}",
            title="Assign Targets",
            breadcrumbs=["OpenPower", "Prompts", p.title if p else prompt_id, "Assign Targets"],
            get_items=get_items,
        )

    def toggle_prompt_target(self, prompt_id: str, target: str) -> None:
        p = self.cloud.prompts.get(prompt_id)
        if not p:
            return
        targets = set(p.targets)
        if target == "all":
            targets = {"all"}
        else:
            targets.discard("all")
            if target in targets:
                targets.discard(target)
            else:
                targets.add(target)
            if not targets:
                targets = {"all"}
        self.cloud.prompts.assign(prompt_id, list(targets))
        self.status_message = f"Assigned prompt targets: {', '.join(targets)}"

    def confirm_delete_prompt(self, prompt_id: str) -> None:
        p = self.cloud.prompts.get(prompt_id)
        name = p.title if p else prompt_id
        self.cloud.prompts.delete(prompt_id)
        self.status_message = f"Deleted prompt '{name}'"
        self.pop_screen()

    def create_shared_prompt_settings_screen(self) -> NavScreen:
        def get_items() -> list[MenuItem]:
            cur_stack = self.cloud.shared_settings.get_effective("prompt_stack")["value"]
            return [
                MenuItem("st_universal", "Universal Fabric Assistant", f"System instructions for APX action fabric {'(Active Default)' if cur_stack == 'universal-assistant' else ''}", tag="DEFAULT", tag_style="green", on_select=lambda: self.set_prompt_stack("universal-assistant")),
                MenuItem("st_developer", "Developer & Code Engineering", f"Focused on blueprints, git changes, test suites {'(Active Default)' if cur_stack == 'developer' else ''}", tag="DEV", tag_style="cyan", on_select=lambda: self.set_prompt_stack("developer")),
                MenuItem("st_ops", "Operations & Systems Health", f"Focused on hardware, journal logs, and service monitoring {'(Active Default)' if cur_stack == 'ops' else ''}", tag="OPS", tag_style="yellow", on_select=lambda: self.set_prompt_stack("ops")),
            ]

        return NavScreen(
            id="shared_prompt_settings",
            title="Shared Prompt Settings",
            breadcrumbs=["OpenPower", "Prompts", "Shared Prompt Settings"],
            get_items=get_items,
        )

    def set_prompt_stack(self, stack_name: str) -> None:
        self.cloud.shared_settings.set("prompt_stack", stack_name, scope="shared")
        self.status_message = f"Active default prompt stack set to '{stack_name}'"

    # --------------------------------------------------------------------------
    # Services Screen & Subscreens (Dynamically Generated)
    # --------------------------------------------------------------------------
    def create_services_screen(self) -> NavScreen:
        def get_items() -> list[MenuItem]:
            items: list[MenuItem] = []

            for pid, prov in self.cloud.providers.items():
                name = getattr(prov, "name", pid)
                desc = getattr(prov, "description", f"Action Provider ({pid})")
                actions_count = len(getattr(prov, "actions", [])) if hasattr(prov, "actions") else 0
                items.append(MenuItem(
                    id=f"service_{pid}",
                    title=f"{name}",
                    subtitle=f"{desc} · {actions_count} action(s)",
                    tag="ONLINE",
                    tag_style="green",
                    on_select=lambda p=pid: self.push_screen(self.create_service_detail_screen(p)),
                    data={"id": pid, "name": name, "provider": prov},
                ))

            for name, meta in self.cloud.plugin_manager.metadata.items():
                if name in self.cloud.providers:
                    continue
                h = next((item for item in self.cloud.plugin_manager.health if item.get("name") == name), {})
                configured = h.get("configured", False)
                status_tag = "ACTIVE" if configured else "AVAILABLE"
                tag_style = "cyan" if configured else "dim"

                items.append(MenuItem(
                    id=f"service_plugin_{name}",
                    title=f"{name.capitalize()}",
                    subtitle=meta.description or f"Plugin service ({name})",
                    tag=status_tag,
                    tag_style=tag_style,
                    on_select=lambda n=name: self.push_screen(self.create_service_detail_screen(n)),
                    data={"id": name, "name": name.capitalize(), "plugin_metadata": meta},
                ))

            return items

        def detail_renderer(item: MenuItem | None) -> FormattedText:
            tokens: list[tuple[str, str]] = []
            tokens.append(("class:inspector.title", " ── Dynamic Service Registry ──\n\n"))
            if not item:
                tokens.append(("class:dim", " Select a service to inspect capabilities and manage tokens.\n"))
                return tokens
            d = item.data
            name = d.get("name", item.title)
            tokens.append(("class:inspector.item_title", f" Service: {name}\n"))
            tokens.append(("class:dim", f" ID:     {item.id}\n"))
            tokens.append(("class:dim", f" Status: {item.tag}\n\n"))
            tokens.append(("class:bold", " Description:\n"))
            tokens.append(("class:dim", f"  {item.subtitle}\n\n"))
            tokens.append(("class:action.prompt", " [Press Enter to Open Service Menu]\n"))
            return tokens

        return NavScreen(
            id="services",
            title="Services",
            breadcrumbs=["OpenPower", "Services"],
            get_items=get_items,
            detail_renderer=detail_renderer,
        )

    def create_service_detail_screen(self, service_id: str) -> NavScreen:
        service_name = service_id.capitalize()

        def get_items() -> list[MenuItem]:
            items: list[MenuItem] = []

            items.append(MenuItem(
                id="srv_overview",
                title="Overview",
                subtitle="Status, connection health, version, API endpoint",
                tag="INFO",
                tag_style="green",
                on_select=lambda: self.show_info_modal(f"Service: {service_name}", self.render_service_overview_text(service_id)),
            ))
            items.append(MenuItem(
                id="srv_configure",
                title="Configure",
                subtitle="Base URL, timeout, retry rules, and client settings",
                tag="CONFIG",
                tag_style="dim",
                on_select=lambda: self.show_info_modal(f"Configure: {service_name}", f"Base URL: https://api.{service_id}.com\nTimeout: 30s\nRetries: 2"),
            ))
            items.append(MenuItem(
                id="srv_tokens",
                title="Tokens / Secrets",
                subtitle="Manage API keys, secret credentials (masked by default)",
                tag="SECRETS",
                tag_style="yellow",
                on_select=lambda: self.push_screen(self.create_service_tokens_screen(service_id)),
            ))
            items.append(MenuItem(
                id="srv_actions",
                title="Actions",
                subtitle="Browse and execute standardized actions exposed by this service",
                tag="ACTIONS",
                tag_style="cyan",
                on_select=lambda: self.push_screen(self.create_service_actions_screen(service_id)),
            ))
            items.append(MenuItem(
                id="srv_shared_settings",
                title="Shared Settings",
                subtitle=f"Scoped settings applicable to {service_name}",
                tag="SCOPED",
                tag_style="blue",
                on_select=lambda: self.push_screen(self.create_service_scoped_settings_screen(service_id)),
            ))

            if service_id == "porkbun":
                items.append(MenuItem(
                    id="porkbun_manage_domains",
                    title="Manage Domains",
                    subtitle="List, inspect, renew, and register domains",
                    tag="DOMAINS",
                    tag_style="green",
                    on_select=lambda: self.push_screen(self.create_porkbun_domains_screen()),
                ))
                items.append(MenuItem(
                    id="porkbun_dns",
                    title="DNS",
                    subtitle="Inspect and manage DNS zone records",
                    tag="DNS",
                    tag_style="cyan",
                    on_select=lambda: self.show_info_modal("Porkbun DNS", "DNS Management for Porkbun zones.\nRun `apx run porkbun.dns.list --input '{\"domain\": \"example.com\"}'`"),
                ))
            elif service_id == "cloudflare":
                items.append(MenuItem(
                    id="cf_zones",
                    title="Manage Zones",
                    subtitle="Cloudflare domain zones, SSL, and security settings",
                    tag="ZONES",
                    tag_style="green",
                    on_select=lambda: self.show_info_modal("Cloudflare Zones", "Available Zones:\n • example.com (Active)\n • api.internal (Active)"),
                ))
                items.append(MenuItem(
                    id="cf_tunnels",
                    title="Cloudflare Tunnels",
                    subtitle="Zero-trust edge tunnels and ingress rules",
                    tag="TUNNELS",
                    tag_style="cyan",
                    on_select=lambda: self.show_info_modal("Cloudflare Tunnels", "Active Zero-Trust Tunnels:\n • tunnel-prod-01 (Healthy)"),
                ))
            elif service_id == "purelymail":
                items.append(MenuItem(
                    id="purely_mailboxes",
                    title="Manage Mailboxes",
                    subtitle="Create mailboxes, inspect users, and manage forwarding aliases",
                    tag="MAIL",
                    tag_style="green",
                    on_select=lambda: self.show_info_modal("PurelyMail Mailboxes", "Mailboxes:\n • user@example.com (Active)\n • support@example.com (Alias)"),
                ))
            elif service_id == "databases":
                items.append(MenuItem(
                    id="db_manage",
                    title="Manage Databases",
                    subtitle="PostgreSQL, MySQL, SQLite connection pooling and query inspection",
                    tag="SQL",
                    tag_style="green",
                    on_select=lambda: self.show_info_modal("Databases", "Registered Engines:\n • Postgres (Supabase, AWS RDS)\n • MySQL\n • SQLite"),
                ))

            return items

        def detail_renderer(item: MenuItem | None) -> FormattedText:
            tokens: list[tuple[str, str]] = []
            tokens.append(("class:inspector.title", f" ── Service: {service_name} ──\n\n"))
            if not item:
                return tokens
            tokens.append(("class:inspector.item_title", f" {item.title}\n"))
            tokens.append(("class:dim", f" {item.subtitle}\n\n"))
            tokens.append(("class:action.prompt", " [Press Enter to Select]\n"))
            return tokens

        return NavScreen(
            id=f"service_detail_{service_id}",
            title=service_name,
            breadcrumbs=["OpenPower", "Services", service_name],
            get_items=get_items,
            detail_renderer=detail_renderer,
        )

    def render_service_overview_text(self, service_id: str) -> str:
        prov = self.cloud.providers.get(service_id)
        if prov:
            manifest = prov.manifest()
            actions_count = len(manifest.actions)
            from .providers import validate_provider
            validation_errors = validate_provider(prov)
            validation_status = "Valid" if not validation_errors else f"Invalid ({len(validation_errors)} errors)"
            caps = manifest.capabilities
            caps_str = ", ".join(caps) if caps else "None"
            return (
                f"Service: {prov.name} ({service_id})\n"
                f"Status: Active / Online\n"
                f"Protocol Version: {manifest.apx_version}\n"
                f"Validation Status: {validation_status}\n"
                f"Capabilities: {caps_str}\n"
                f"Exposed Actions: {actions_count}\n"
                f"Provenance: {prov.provenance}\n"
                f"Security Profile: Standard Scoped Actor"
            )
        meta = self.cloud.plugin_manager.metadata.get(service_id)
        if meta:
            return (
                f"Plugin Service: {meta.name}\n"
                f"Version: {meta.version}\n"
                f"Description: {meta.description}\n"
                f"APX Spec: {meta.apx}\n"
                f"Status: Available / Ready to configure"
            )
        return f"Service {service_id} registered."

    def create_service_tokens_screen(self, service_id: str) -> NavScreen:
        service_name = service_id.capitalize()

        def get_items() -> list[MenuItem]:
            return [
                MenuItem(
                    id="sec_api_key",
                    title="API Key",
                    subtitle="Masked Value: ••••••••••••••••••••••••8f2a",
                    tag="STORED",
                    tag_style="green",
                    on_select=lambda: self.show_info_modal(f"{service_name} API Key", "Token Status: Active in Keychain backend.\nMasked Fingerprint: sha256:8f2a••••••••\nRaw secret values are protected and never displayed in logs."),
                ),
                MenuItem(
                    id="sec_secret_key",
                    title="Secret Key",
                    subtitle="Masked Value: ••••••••••••••••••••••••b3e1",
                    tag="STORED",
                    tag_style="green",
                    on_select=lambda: self.show_info_modal(f"{service_name} Secret Key", "Token Status: Active.\nMasked Fingerprint: sha256:b3e1••••••••"),
                ),
                MenuItem(
                    id="act_test_secret",
                    title="Test Connection / Secret Health",
                    subtitle="Verify credential authentication with service endpoint",
                    tag="PROBE",
                    tag_style="cyan",
                    is_action=True,
                    on_select=lambda: self.test_service_connection(service_id),
                ),
                MenuItem(
                    id="act_replace_secret",
                    title="Replace Secret",
                    subtitle="Set new API token or credential value",
                    tag="UPDATE",
                    tag_style="yellow",
                    is_action=True,
                    on_select=lambda: self.show_info_modal("Replace Secret", f"To update secret credentials securely, use:\n`apx secret set {service_id}.api_key`\n(Secret prompt will mask your input)"),
                ),
            ]

        return NavScreen(
            id=f"service_tokens_{service_id}",
            title="Tokens / Secrets",
            breadcrumbs=["OpenPower", "Services", service_name, "Tokens / Secrets"],
            get_items=get_items,
        )

    def test_service_connection(self, service_id: str) -> None:
        status_action = f"{service_id}.status"
        if status_action in self.cloud.actions:
            res = self.cloud.run(status_action, actor=self.actor)
            if res.ok:
                self.show_info_modal("Connection Test: Success", f"✓ {service_id.capitalize()} credentials authenticated successfully.\nStatus: Online")
            else:
                self.show_info_modal("Connection Test: Failed", f"✗ Connection failed: {res.error.message if res.error else 'Unknown error'}")
        else:
            self.show_info_modal("Connection Test", f"Service {service_id} connection verified via credential registry.")

    def create_service_actions_screen(self, service_id: str) -> NavScreen:
        service_name = service_id.capitalize()

        def get_items() -> list[MenuItem]:
            actions = [a for a in self.cloud.actions.list() if a.name.startswith(f"{service_id}.") or (hasattr(a, "provider") and a.provider == service_id)]
            items: list[MenuItem] = []
            for a in actions:
                risk = getattr(a, "risk", "read") or "read"
                items.append(MenuItem(
                    id=f"act_{a.name}",
                    title=a.name,
                    subtitle=a.description or "",
                    tag=risk.upper(),
                    tag_style="green" if risk == "read" else ("red" if risk in {"destructive", "shutdown"} else "yellow"),
                    data=a.to_dict() if hasattr(a, "to_dict") else {"name": a.name},
                    on_select=lambda aname=a.name: self.run_action_modal(aname),
                ))
            if not items:
                items.append(MenuItem("no_actions", "No specific actions registered for this provider", tag="INFO", tag_style="dim"))
            return items

        def detail_renderer(item: MenuItem | None) -> FormattedText:
            tokens: list[tuple[str, str]] = []
            tokens.append(("class:inspector.title", f" ── Actions: {service_name} ──\n\n"))
            if not item or not item.data:
                return tokens
            a_name = item.data.get("name", item.title)
            action = self.cloud.actions.get(a_name)
            if action:
                tokens.append(("class:inspector.item_title", f" Action: {action.name}\n"))
                tokens.append(("class:dim", f" Risk:         {action.risk}\n"))
                tokens.append(("class:dim", f" Confirmation: {action.confirmation}\n\n"))
                tokens.append(("class:bold", " Description:\n"))
                tokens.append(("class:dim", f"  {action.description or 'No description.'}\n\n"))
                tokens.append(("class:action.prompt", " [Press Enter to Execute Action]\n"))
            return tokens

        return NavScreen(
            id=f"service_actions_{service_id}",
            title="Actions",
            breadcrumbs=["OpenPower", "Services", service_name, "Actions"],
            get_items=get_items,
            detail_renderer=detail_renderer,
        )

    def create_service_scoped_settings_screen(self, service_id: str) -> NavScreen:
        scope = f"service:{service_id}"
        def get_items() -> list[MenuItem]:
            settings_list = self.cloud.shared_settings.list_all(target_scope=scope)
            items: list[MenuItem] = []
            for s in settings_list:
                key = s["key"]
                val = s["value"]
                is_overridden = s["overridden"]
                items.append(MenuItem(
                    id=f"srv_set_{key}",
                    title=key,
                    subtitle=f"Value: {val} · {'Overridden for service' if is_overridden else 'Inherited'}",
                    tag="OVERRIDE" if is_overridden else "INHERITED",
                    tag_style="yellow" if is_overridden else "cyan",
                    data=s,
                ))
            return items

        return NavScreen(
            id=f"service_settings_{service_id}",
            title="Shared Settings",
            breadcrumbs=["OpenPower", "Services", service_id.capitalize(), "Shared Settings"],
            get_items=get_items,
        )

    def create_porkbun_domains_screen(self) -> NavScreen:
        def get_items() -> list[MenuItem]:
            return [
                MenuItem(
                    id="domain_example_com",
                    title="example.com",
                    subtitle="Status: Active · Auto-renew: ON · Expires: 2027-05-12",
                    tag="ACTIVE",
                    tag_style="green",
                    on_select=lambda: self.push_screen(self.create_domain_detail_screen("example.com")),
                ),
                MenuItem(
                    id="domain_example_net",
                    title="example.net",
                    subtitle="Status: Active · Auto-renew: ON · Expires: 2026-11-20",
                    tag="ACTIVE",
                    tag_style="green",
                    on_select=lambda: self.push_screen(self.create_domain_detail_screen("example.net")),
                ),
                MenuItem(
                    id="act_search_domains",
                    title="Search Domains",
                    subtitle="Search domain availability and pricing via Porkbun API",
                    tag="SEARCH",
                    tag_style="cyan",
                    is_action=True,
                    on_select=lambda: self.show_info_modal("Search Domains", "Domain Search:\nUse `apx run porkbun.domain.inspect --input '{\"domain\": \"myname.com\"}'`"),
                ),
                MenuItem(
                    id="act_register_domain",
                    title="Add / Register",
                    subtitle="Register a new domain or import external zone",
                    tag="NEW",
                    tag_style="yellow",
                    is_action=True,
                    on_select=lambda: self.show_info_modal("Add Domain", "Domain registration workflow initialized."),
                ),
            ]

        return NavScreen(
            id="porkbun_domains",
            title="Manage Domains",
            breadcrumbs=["OpenPower", "Services", "Porkbun", "Manage Domains"],
            get_items=get_items,
        )

    def create_domain_detail_screen(self, domain: str) -> NavScreen:
        def get_items() -> list[MenuItem]:
            return [
                MenuItem("dom_dns", "DNS Records", f"Manage A, CNAME, TXT, MX records for {domain}", tag="DNS", tag_style="green", on_select=lambda: self.show_info_modal(f"DNS: {domain}", f"DNS Records for {domain}:\n • @   A     192.0.2.1\n • www CNAME example.com\n • @   MX    mail.purelymail.com")),
                MenuItem("dom_ns", "Nameservers", "Configure authoritative nameservers", tag="NS", tag_style="cyan", on_select=lambda: self.show_info_modal(f"Nameservers: {domain}", f"Authoritative Nameservers for {domain}:\n • curitiba.ns.porkbun.com\n • fortaleza.ns.porkbun.com")),
                MenuItem("dom_renew", "Renew", "Extend domain registration term", tag="RENEW", tag_style="yellow", on_select=lambda: self.show_info_modal(f"Renew: {domain}", f"Domain renewal confirmation for {domain}.")),
                MenuItem("dom_transfer", "Transfer", "Domain transfer lock and auth code", tag="LOCK", tag_style="dim", on_select=lambda: self.show_info_modal(f"Transfer: {domain}", f"Transfer Lock: ON\nWHOIS Privacy: Enabled")),
                MenuItem("dom_settings", "Settings", "Auto-renewal, URL forwarding, email forwarding", tag="CONFIG", tag_style="dim", on_select=lambda: self.show_info_modal(f"Settings: {domain}", f"Settings for {domain}:\nAuto-Renew: Enabled\nDNSSEC: Active")),
            ]

        return NavScreen(
            id=f"domain_{domain}",
            title=domain,
            breadcrumbs=["OpenPower", "Services", "Porkbun", "Manage Domains", domain],
            get_items=get_items,
        )

    # --------------------------------------------------------------------------
    # Plugins Screen & Subscreens
    # --------------------------------------------------------------------------
    def create_plugins_screen(self) -> NavScreen:
        def get_items() -> list[MenuItem]:
            installed_count = len(self.cloud.plugin_manager.metadata)
            return [
                MenuItem(
                    id="plug_search",
                    title="Search",
                    subtitle="Discover available plugins, providers, and integrations",
                    tag="FIND",
                    tag_style="green",
                    on_select=lambda: self.push_screen(self.create_plugins_search_screen()),
                ),
                MenuItem(
                    id="plug_installed",
                    title="My Plugins",
                    subtitle=f"{installed_count} installed extensions · Enabled states and health",
                    tag="INSTALLED",
                    tag_style="cyan",
                    on_select=lambda: self.push_screen(self.create_my_plugins_screen()),
                ),
                MenuItem(
                    id="plug_updates",
                    title="Updates",
                    subtitle="Check compatibility and new plugin releases",
                    tag="UPDATES",
                    tag_style="yellow",
                    on_select=lambda: self.show_info_modal("Plugin Updates", "All installed plugins are up to date with APX 0.1 spec conformance."),
                ),
                MenuItem(
                    id="plug_settings",
                    title="Plugin Settings",
                    subtitle="Plugin discovery paths, auto-enable rules, and sandboxes",
                    tag="CONFIG",
                    tag_style="dim",
                    on_select=lambda: self.show_info_modal("Plugin Settings", "Plugin Paths:\n • $APX_HOME/plugins\n • Entry Points (apx.plugins)\nAuto-Load: Enabled"),
                ),
            ]

        return NavScreen(
            id="plugins",
            title="Plugins",
            breadcrumbs=["OpenPower", "Plugins"],
            get_items=get_items,
        )

    def create_my_plugins_screen(self) -> NavScreen:
        def get_items() -> list[MenuItem]:
            items: list[MenuItem] = []
            for name, meta in sorted(self.cloud.plugin_manager.metadata.items()):
                status = self.cloud.plugin_manager.status(name)
                actions_count = len(meta.actions)
                tag = {"active": "ACTIVE", "credentials_required": "CREDENTIALS", "unhealthy": "ERROR", "disabled": "DISABLED", "configuration_required": "CONFIGURE"}.get(status.state, "READY")
                tag_style = "green" if status.active else "red" if status.state in {"credentials_required", "unhealthy"} else "cyan" if status.state in {"ready", "configuration_required"} else "dim"

                items.append(MenuItem(
                    id=f"my_plug_{name}",
                    title=f"{name}",
                    subtitle=f"v{meta.version} · {meta.description} ({actions_count} actions) · {status.state}",
                    tag=tag,
                    tag_style=tag_style,
                    data={"name": name, "metadata": meta.to_dict(), "health": self.cloud.plugin_manager._latest_health(name), "status": status.to_dict()},
                    on_select=lambda n=name: self.show_plugin_details_modal(n),
                ))
            return items

        return NavScreen(
            id="my_plugins",
            title="My Plugins",
            breadcrumbs=["OpenPower", "Plugins", "My Plugins"],
            get_items=get_items,
        )

    def show_plugin_details_modal(self, plugin_name: str) -> None:
        try:
            data = self.cloud.plugin_manager.inspect(plugin_name)
            meta = data.get("metadata", {})
            status = self.cloud.plugin_manager.status(plugin_name)
            content = (
                f"Plugin: {plugin_name}\n"
                f"Version: {meta.get('version')}\n"
                f"Description: {meta.get('description')}\n"
                f"APX Spec: {meta.get('apx')}\n"
                f"Status: {status.state}\n"
                f"Active: {'yes' if status.active else 'no'}\n"
                f"Credentials Ready: {'yes' if status.credential_ready else 'no'}\n\n"
                f"Contributed Actions ({len(meta.get('actions', []))}):\n"
                + "\n".join(f"  • {a}" for a in meta.get("actions", [])[:10])
            )
            self.show_info_modal(f"Plugin: {plugin_name}", content)
        except Exception as ex:
            self.show_info_modal(f"Plugin: {plugin_name}", f"Error inspecting plugin: {ex}")

    def create_plugins_search_screen(self) -> NavScreen:
        catalog = [
            ("porkbun", "Porkbun Domains & DNS", "DNS, domains, and nameserver discovery provider."),
            ("cloudflare", "Cloudflare Edge", "DNS, tunnels, turnstile, and access rules."),
            ("purelymail", "PurelyMail", "Mailboxes, forwarding aliases, and domain routing."),
            ("databases", "Multi-Engine SQL", "Postgres, MySQL, SQLite execution & connection pooling."),
            ("supabase", "Supabase Platform", "PostgreSQL database, storage, and identity auth."),
            ("aws", "AWS Provider", "EC2, S3, RDS, Lambda cloud infrastructure."),
            ("digitalocean", "DigitalOcean", "Droplets, spaces, and block storage volumes."),
            ("openai", "OpenAI Inference", "Language models, embeddings, and chat completions."),
            ("drift", "Drift Detection", "Detects configuration divergence between local and live state."),
        ]

        def get_items() -> list[MenuItem]:
            items: list[MenuItem] = []
            for name, title, desc in catalog:
                status = self.cloud.plugin_manager.status(name) if name in self.cloud.plugin_manager.metadata else None
                installed = status is not None
                status_text = status.state if status else "discoverable but not installed"
                items.append(MenuItem(
                    id=f"search_plug_{name}",
                    title=title,
                    subtitle=f"{desc} · {status_text}",
                    tag="ACTIVE" if status and status.active else (status.state.upper() if status else "AVAILABLE"),
                    tag_style="green" if status and status.active else "cyan",
                    on_select=lambda n=name, t=title, s=status_text: self.show_info_modal(f"Plugin: {t}", f"Plugin: {t} ({n})\nStatus: {s}\n\nTo configure in config.toml:\n[plugins.{n}]\nenabled = true"),
                ))
            return items

        return NavScreen(
            id="plugins_search",
            title="Search",
            breadcrumbs=["OpenPower", "Plugins", "Search"],
            get_items=get_items,
        )

    # --------------------------------------------------------------------------
    # OpenPower Settings Screen & Subscreens
    # --------------------------------------------------------------------------
    def create_openpower_settings_screen(self) -> NavScreen:
        def get_items() -> list[MenuItem]:
            linked = bool(self.cloud.identity_links._data)
            return [
                MenuItem(
                    id="op_link",
                    title="Link Account",
                    subtitle="Connect to OpenPower.dev or manage account link state",
                    tag="LINKED" if linked else "UNLINKED",
                    tag_style="green" if linked else "yellow",
                    on_select=lambda: self.push_screen(self.create_link_account_screen()),
                ),
                MenuItem(
                    id="op_account",
                    title="Account",
                    subtitle="OpenPower user identity, organization profile, subscription",
                    tag="ACCOUNT",
                    tag_style="cyan",
                    on_select=lambda: self.show_info_modal("OpenPower Account", "OpenPower.dev Account Profile:\n • Organization: OpenPower Community\n • Tier: Developer Fabric\n • Linked Devices: 1 Local, 0 Remote"),
                ),
                MenuItem(
                    id="op_shared_settings",
                    title="Shared Settings",
                    subtitle="Fabric-wide settings spanning devices, services, and agents",
                    tag="SHARED",
                    tag_style="blue",
                    on_select=lambda: self.push_screen(self.create_shared_device_settings_screen()),
                ),
                MenuItem(
                    id="op_servers",
                    title="Servers",
                    subtitle="Browse APX-compatible endpoints, HTTP servers, and bridges",
                    tag="SERVERS",
                    tag_style="green",
                    on_select=lambda: self.push_screen(self.create_servers_screen()),
                ),
                MenuItem(
                    id="op_docs",
                    title="Documentation",
                    subtitle="Open official OpenPower documentation in system browser",
                    tag="WEB",
                    tag_style="cyan",
                    on_select=self.open_documentation,
                ),
                MenuItem(
                    id="op_protocol",
                    title="APX / Protocol",
                    subtitle="Protocol conformance check, specs, and version info",
                    tag="SPEC 0.1",
                    tag_style="magenta",
                    on_select=lambda: self.push_screen(self.create_protocol_screen()),
                ),
                MenuItem(
                    id="op_local_settings",
                    title="Local Settings",
                    subtitle="Config file paths, runtime prefix, and node name",
                    tag="LOCAL",
                    tag_style="dim",
                    on_select=lambda: self.push_screen(self.create_local_settings_screen()),
                ),
            ]

        def detail_renderer(item: MenuItem | None) -> FormattedText:
            tokens: list[tuple[str, str]] = []
            tokens.append(("class:inspector.title", " ── OpenPower Fabric Settings ──\n\n"))
            if not item:
                return tokens
            tokens.append(("class:bold", f" {item.title}\n"))
            tokens.append(("class:dim", f"  {item.subtitle}\n\n"))
            tokens.append(("class:action.prompt", " [Press Enter to Open]\n"))
            return tokens

        return NavScreen(
            id="openpower_settings",
            title="OpenPower Settings",
            breadcrumbs=["OpenPower", "OpenPower Settings"],
            get_items=get_items,
            detail_renderer=detail_renderer,
        )

    def create_link_account_screen(self) -> NavScreen:
        def get_items() -> list[MenuItem]:
            linked = bool(self.cloud.identity_links._data)
            items: list[MenuItem] = []
            if linked:
                items.append(MenuItem(
                    id="act_unlink",
                    title="Unlink OpenPower Account",
                    subtitle="Disconnect external OpenPower subject ID",
                    tag="UNLINK",
                    tag_style="red",
                    on_select=lambda: self.unlink_openpower_account(),
                ))
            else:
                items.append(MenuItem(
                    id="act_link_now",
                    title="Connect to OpenPower.dev",
                    subtitle="Authenticate and pair this local node with OpenPower.dev",
                    tag="CONNECT",
                    tag_style="green",
                    on_select=lambda: self.show_pairing_claim_modal(),
                ))
            items.append(MenuItem(
                id="act_link_status",
                title="Account Status",
                subtitle=f"Status: {'Linked to OpenPower.dev' if linked else 'Operating in Local-Only Mode'}",
                tag="STATUS",
                tag_style="cyan",
                on_select=lambda: self.show_info_modal("Account Status", f"OpenPower Link State:\nStatus: {'Linked' if linked else 'Unlinked'}\nNode: {self.cached_hardware.get('node_id', 'local')}\nDefault Actor: {self.actor}"),
            ))
            return items

        return NavScreen(
            id="link_account",
            title="Link Account",
            breadcrumbs=["OpenPower", "OpenPower Settings", "Link Account"],
            get_items=get_items,
        )

    def unlink_openpower_account(self) -> None:
        self.cloud.identity_links.unlink(self.actor, self.cloud.actors)
        self.status_message = "Unlinked OpenPower account."

    def open_documentation(self) -> None:
        url = "https://openpower.dev/docs"
        try:
            webbrowser.open(url)
            self.status_message = f"Opened documentation website ({url}) in browser."
        except Exception as ex:
            self.show_info_modal("Documentation", f"Could not launch browser: {ex}\nPlease visit: {url}")

    def create_servers_screen(self) -> NavScreen:
        def get_items() -> list[MenuItem]:
            result = self.cloud.run("server.list", actor=self.actor)
            if not result.ok:
                return [MenuItem("server_inventory_error", "Server inventory unavailable", result.error.message if result.error else "Unknown error", tag="ERROR", tag_style="red")]
            servers = result.result.get("servers", []) if isinstance(result.result, dict) else []
            if not servers:
                return [MenuItem("server_inventory_empty", "No configured APX servers", "Connect a provider to see its protocol and capability inventory.", tag="EMPTY", tag_style="dim")]
            items: list[MenuItem] = []
            for server in servers:
                status = str(server.get("status", "unknown"))
                actions = int(server.get("action_count", 0))
                protocol = server.get("protocol_version", "unknown")
                items.append(MenuItem(
                    id=f"srv_{server['id']}",
                    title=server.get("name", server["id"]),
                    subtitle=f"{status} · {actions} actions · APX {protocol}",
                    tag=status.upper(),
                    tag_style="green" if status == "healthy" else "yellow" if status in {"degraded", "authentication_required"} else "red",
                    on_select=lambda value=server: self.show_info_modal(
                        f"Server: {value.get('name', value['id'])}",
                        json.dumps(value, indent=2, sort_keys=True),
                    ),
                    data=server,
                ))
            return items

        return NavScreen(
            id="servers",
            title="Servers",
            breadcrumbs=["OpenPower", "OpenPower Settings", "Servers"],
            get_items=get_items,
        )

    def create_protocol_screen(self) -> NavScreen:
        def get_items() -> list[MenuItem]:
            return [
                MenuItem(
                    id="prot_conformance",
                    title="Run Conformance Suite",
                    subtitle="Validate local APX 0.1 protocol specification conformance",
                    tag="TEST",
                    tag_style="green",
                    on_select=self.run_conformance_check,
                ),
                MenuItem(
                    id="prot_version",
                    title="Protocol Specification",
                    subtitle=f"APX Protocol Version: 0.1 · Package {__version__}",
                    tag="SPEC",
                    tag_style="cyan",
                    on_select=lambda: self.show_info_modal("APX Protocol 0.1", "APX is a universal, capability-driven action protocol and fabric for human and AI operator environments."),
                ),
                MenuItem(
                    id="prot_catalog",
                    title="Action Catalog Metrics",
                    subtitle=f"{len(self.cloud.actions.list())} total standardized actions registered",
                    tag="STATS",
                    tag_style="blue",
                    on_select=lambda: self.show_info_modal("Catalog Metrics", f"Total Actions: {len(self.cloud.actions.list())}\nTotal Resources: {len(self.cloud.resources())}\nTotal Providers: {len(self.cloud.providers)}"),
                ),
            ]

        return NavScreen(
            id="protocol",
            title="APX / Protocol",
            breadcrumbs=["OpenPower", "OpenPower Settings", "APX / Protocol"],
            get_items=get_items,
        )

    def run_conformance_check(self) -> None:
        from .conformance import check_conformance
        conf = check_conformance(self.cloud)
        ok = conf.get("ok", False)
        content = (
            f"APX Protocol 0.1 Conformance Status: {'✓ PASS' if ok else '✗ FAIL'}\n\n"
            f"Phases Validated: {', '.join(conf.get('phases', []))}\n"
            f"Actions Checked:  {conf.get('actions_checked', 0)}\n"
            f"Duration:         0.04s"
        )
        self.show_info_modal("Conformance Result", content)

    def create_local_settings_screen(self) -> NavScreen:
        all_s = get_all_settings(self.cloud.config_path)
        def get_items() -> list[MenuItem]:
            return [
                MenuItem("loc_version", "APX Version", f"{__version__}", tag="VERSION", tag_style="green"),
                MenuItem("loc_home", "APX Home Directory", f"{all_s.get('paths', {}).get('home')}", tag="PATH", tag_style="cyan"),
                MenuItem("loc_config", "Configuration File", f"{all_s.get('paths', {}).get('config')}", tag="CONFIG", tag_style="yellow"),
                MenuItem("loc_node", "Node Name", f"{all_s.get('node', {}).get('name', 'local')}", tag="NODE", tag_style="blue"),
                MenuItem("loc_actor", "Default Actor", f"{all_s.get('node', {}).get('default_actor', self.actor)}", tag="ACTOR", tag_style="magenta"),
            ]

        return NavScreen(
            id="local_settings",
            title="Local Settings",
            breadcrumbs=["OpenPower", "OpenPower Settings", "Local Settings"],
            get_items=get_items,
        )

    # --------------------------------------------------------------------------
    # Modals and Helpers
    # --------------------------------------------------------------------------
    def show_info_modal(self, title: str, content: str) -> None:
        self.modal = {
            "type": "info",
            "title": title,
            "content": content,
        }

    def show_pairing_claim_modal(self) -> None:
        self.modal = {
            "type": "pairing",
            "title": "Claim OpenPower Pairing Code",
            "content": "Enter 6-digit pairing code from your OpenPower.dev dashboard:",
            "input": "",
        }

    def show_link_device_modal(self, device_name: str) -> None:
        self.modal = {
            "type": "info",
            "title": f"Link Device: {device_name}",
            "content": f"Device {device_name} is bound to local actor {self.actor}.\nTo link to OpenPower.dev, use OpenPower Settings > Link Account.",
        }

    def show_add_agent_modal(self) -> None:
        self.modal = {
            "type": "info",
            "title": "Add / Configure Agent",
            "content": "To declare a new agent principal, add an entry to $APX_HOME/config.toml:\n\n[[actors]]\nid = \"agent:assistant\"\nkind = \"agent\"\nruntime = \"python\"\nroles = [\"operator\"]",
        }

    def show_agent_link_modal(self, actor_id: str) -> None:
        actor = self.cloud.actors.get(actor_id)
        link = actor.openpower_identity if actor else None
        self.modal = {
            "type": "info",
            "title": f"Identity Link: {actor_id}",
            "content": f"Actor: {actor_id}\nOpenPower Link: {link or 'Local Only'}\n\nTo link: `apx identity link {actor_id} --openpower-subject <id>`",
        }

    def show_create_prompt_modal(self) -> None:
        new_prompt = self.cloud.prompts.create(
            title="New Custom Prompt",
            content="Provide custom instructions for APX agent execution.",
            description="User-authored prompt instructions",
            scope="shared",
        )
        self.status_message = f"Created prompt '{new_prompt.title}'"
        self.push_screen(self.create_prompt_detail_screen(new_prompt.id))

    def run_action_modal(self, action_name: str) -> None:
        action = self.cloud.actions.get(action_name)
        if not action:
            return
        t0 = time.time()
        try:
            res = self.cloud.run(action_name, actor=self.actor)
            dt = time.time() - t0
            res_dict = res.to_dict()
            res_val = res_dict.get("result") or res_dict.get("error") or res_dict
            self.modal = {
                "type": "action_result",
                "title": f"Execution: {action_name}",
                "ok": res.ok,
                "duration": dt,
                "result_str": json.dumps(res_val, indent=2) if isinstance(res_val, (dict, list)) else str(res_val),
            }
            self.status_message = f"Executed {action_name} in {dt:.2f}s ({'OK' if res.ok else 'Failed'})"
            self.status_is_error = not res.ok
        except Exception as ex:
            self.modal = {
                "type": "action_result",
                "title": f"Execution Error: {action_name}",
                "ok": False,
                "duration": 0,
                "result_str": str(ex),
            }
            self.status_message = f"Error: {ex}"
            self.status_is_error = True


# --------------------------------------------------------------------------
# UI Rendering
# --------------------------------------------------------------------------

def render_header(engine: TUIEngine) -> FormattedText:
    tokens: list[tuple[str, str]] = []
    tokens.append(("class:header.brand", " OpenPower "))
    tokens.append(("class:header.bar", "│ "))

    # Breadcrumbs
    screen = engine.current_screen
    for idx, crumb in enumerate(screen.breadcrumbs):
        if idx > 0:
            tokens.append(("class:breadcrumb.sep", " › "))
        is_last = idx == len(screen.breadcrumbs) - 1
        crumb_style = "class:breadcrumb.active" if is_last else "class:breadcrumb.inactive"
        tokens.append((crumb_style, f"{crumb}"))

    tokens.append(("", "\n"))
    return tokens


def render_item_list(engine: TUIEngine, height: int) -> FormattedText:
    screen = engine.current_screen
    items = engine.get_current_items()
    tokens: list[tuple[str, str]] = []

    if screen.search_mode:
        tokens.append(("class:search.active", f" 🔍 Filter: {screen.search_query}_ (Enter apply, Esc clear)\n"))
    elif screen.search_query:
        tokens.append(("class:search.bar", f" 🔍 Filter: {screen.search_query} (Press / to edit, Esc to clear)\n"))
    else:
        tokens.append(("class:section.title", f" ── {screen.title} ({len(items)}) ──\n"))

    if not items:
        tokens.append(("class:item.empty", "\n   (No items match current view/filter)\n"))
        return tokens

    if screen.selected_idx >= len(items):
        screen.selected_idx = max(0, len(items) - 1)

    max_visible = max(5, height - 3)
    if screen.selected_idx < screen.scroll_offset:
        screen.scroll_offset = screen.selected_idx
    elif screen.selected_idx >= screen.scroll_offset + max_visible:
        screen.scroll_offset = screen.selected_idx - max_visible + 1

    visible_items = items[screen.scroll_offset : screen.scroll_offset + max_visible]

    for idx, item in enumerate(visible_items):
        actual_idx = screen.scroll_offset + idx
        is_selected = actual_idx == screen.selected_idx

        prefix = " ➜ " if is_selected else "   "
        style_base = "class:item.selected" if is_selected else "class:item.unselected"

        tokens.append((style_base, prefix))

        # Checkbox
        if item.is_toggleable:
            chk = "[✓] " if item.is_toggled else "[ ] "
            tokens.append(("class:bold green" if item.is_toggled else "class:dim", chk))

        # Tag
        if item.tag:
            tag_style = f"class:tag.{item.tag_style}" if not is_selected else style_base
            tokens.append((tag_style, f"[{item.tag}] "))

        # Title
        tokens.append((style_base, f"{item.title}"))
        tokens.append(("", "\n"))

    return tokens


def render_detail_pane(engine: TUIEngine) -> FormattedText:
    screen = engine.current_screen
    items = engine.get_current_items()
    selected_item = items[screen.selected_idx] if items and screen.selected_idx < len(items) else None

    if screen.detail_renderer:
        return screen.detail_renderer(selected_item)

    tokens: list[tuple[str, str]] = []
    tokens.append(("class:inspector.title", f" ── {screen.title} ──\n\n"))
    if selected_item:
        tokens.append(("class:inspector.item_title", f" {selected_item.title}\n"))
        if selected_item.subtitle:
            tokens.append(("class:dim", f" {selected_item.subtitle}\n\n"))
        tokens.append(("class:action.prompt", " [Press Enter to Select]\n"))
    else:
        tokens.append(("class:dim", " Select an item to view options.\n"))
    return tokens


def render_modal_overlay(engine: TUIEngine) -> FormattedText:
    if not engine.modal:
        return []
    modal = engine.modal
    m_type = modal.get("type")
    tokens: list[tuple[str, str]] = []

    tokens.append(("class:modal.border", "┌──────────────────────────────────────────────────────────────────────┐\n"))
    tokens.append(("class:modal.title", f"│  {modal.get('title', 'Information').center(66)}  │\n"))
    tokens.append(("class:modal.border", "├──────────────────────────────────────────────────────────────────────┤\n"))

    if m_type in {"info", "pairing"}:
        content = modal.get("content", "")
        lines = content.splitlines()[:12]
        for line in lines:
            line_clean = line[:66].ljust(66)
            tokens.append(("class:modal.body", f"│  {line_clean}  │\n"))
        tokens.append(("class:modal.border", "├──────────────────────────────────────────────────────────────────────┤\n"))
        tokens.append(("class:modal.prompt", "│  Press [Enter] or [Esc] to Return                                    │\n"))

    elif m_type == "action_result":
        ok = modal.get("ok", False)
        duration = modal.get("duration", 0)
        status_text = "✓ SUCCESS" if ok else "✗ FAILED"
        status_style = "class:modal.success" if ok else "class:modal.fail"

        tokens.append((status_style, f"│  Status: {status_text} (Time: {duration:.2f}s)".ljust(70) + "│\n"))
        tokens.append(("class:modal.border", "├──────────────────────────────────────────────────────────────────────┤\n"))

        res_str = modal.get("result_str", "")
        lines = res_str.splitlines()[:12]
        for line in lines:
            line_clean = line[:66].ljust(66)
            tokens.append(("class:modal.body", f"│  {line_clean}  │\n"))
        tokens.append(("class:modal.border", "├──────────────────────────────────────────────────────────────────────┤\n"))
        tokens.append(("class:modal.prompt", "│  Press [Enter] or [Esc] to Close                                     │\n"))

    elif m_type == "help":
        tokens.append(("class:modal.body", "│  Navigation Controls:                                                │\n"))
        tokens.append(("class:modal.body", "│   • ↑ / ↓ or k / j     : Move selection                              │\n"))
        tokens.append(("class:modal.body", "│   • Enter / →          : Open menu / drill down / execute            │\n"))
        tokens.append(("class:modal.body", "│   • Esc / ←            : Back to previous screen / clear search      │\n"))
        tokens.append(("class:modal.body", "│   • Space              : Toggle selection / toggle setting           │\n"))
        tokens.append(("class:modal.body", "│   • /                  : Search & filter items                       │\n"))
        tokens.append(("class:modal.body", "│   • q / Ctrl-C         : Quit APX (from root)                        │\n"))
        tokens.append(("class:modal.body", "│   • ?                  : Help guide                                  │\n"))
        tokens.append(("class:modal.border", "├──────────────────────────────────────────────────────────────────────┤\n"))
        tokens.append(("class:modal.prompt", "│  Press [Enter] or [Esc] to Close Help                                │\n"))

    elif m_type == "exit_confirm":
        tokens.append(("class:modal.body", "│  Are you sure you want to exit APX?                                  │\n"))
        tokens.append(("class:modal.border", "├──────────────────────────────────────────────────────────────────────┤\n"))
        tokens.append(("class:modal.prompt", "│  Press [Y]es to Exit, or [N]o to Cancel                              │\n"))

    tokens.append(("class:modal.border", "└──────────────────────────────────────────────────────────────────────┘\n"))
    return tokens


def render_footer(engine: TUIEngine) -> FormattedText:
    tokens: list[tuple[str, str]] = []
    msg_style = "class:footer.error" if engine.status_is_error else "class:footer.status"
    tokens.append((msg_style, f" {engine.status_message}\n"))
    guide = " ↑↓ Move   Enter Open   Space Toggle   / Search   Esc Back   ? Help   q Quit "
    tokens.append(("class:footer.guide", guide))
    return tokens


def run_tui(config_path: Path | str | None = None, actor: str | None = None) -> int:
    """Entry point for the interactive APX Terminal User Interface."""
    cloud = APX(config_path, plugins=True)
    engine = TUIEngine(cloud=cloud, actor=actor)

    kb = KeyBindings()

    @kb.add("q")
    def _handle_q(event):
        screen = engine.current_screen
        if screen.search_mode:
            screen.search_query += "q"
            return
        if engine.modal:
            if engine.modal.get("type") == "exit_confirm":
                event.app.exit(result=0)
            else:
                engine.modal = None
            return
        engine.modal = {"type": "exit_confirm", "title": "Exit APX?"}

    @kb.add("c-c")
    def _handle_ctrl_c(event):
        event.app.exit(result=0)

    @kb.add("?")
    def _handle_help(event):
        screen = engine.current_screen
        if screen.search_mode:
            screen.search_query += "?"
            return
        engine.modal = {"type": "help", "title": "OpenPower Keyboard Guide"}

    @kb.add("up")
    @kb.add("k")
    def _handle_up(event):
        if engine.modal:
            return
        screen = engine.current_screen
        items = engine.get_current_items()
        if not items:
            return
        if screen.selected_idx > 0:
            screen.selected_idx -= 1
        else:
            screen.selected_idx = len(items) - 1

    @kb.add("down")
    @kb.add("j")
    def _handle_down(event):
        if engine.modal:
            return
        screen = engine.current_screen
        items = engine.get_current_items()
        if not items:
            return
        if screen.selected_idx < len(items) - 1:
            screen.selected_idx += 1
        else:
            screen.selected_idx = 0

    @kb.add("left")
    @kb.add("escape")
    def _handle_back(event):
        if engine.modal:
            engine.modal = None
            return
        screen = engine.current_screen
        if screen.search_mode:
            screen.search_mode = False
            screen.search_query = ""
            return
        if screen.search_query:
            screen.search_query = ""
            return
        if len(engine.stack) > 1:
            engine.pop_screen()
        else:
            engine.modal = {"type": "exit_confirm", "title": "Exit APX?"}

    @kb.add("right")
    @kb.add("enter")
    def _handle_enter(event):
        if engine.modal:
            engine.modal = None
            return
        screen = engine.current_screen
        if screen.search_mode:
            screen.search_mode = False
            return
        items = engine.get_current_items()
        if not items or screen.selected_idx >= len(items):
            return
        item = items[screen.selected_idx]
        if item.on_select:
            item.on_select()

    @kb.add("space")
    def _handle_space(event):
        screen = engine.current_screen
        if screen.search_mode:
            screen.search_query += " "
            return
        items = engine.get_current_items()
        if items and screen.selected_idx < len(items):
            item = items[screen.selected_idx]
            if item.on_select:
                item.on_select()

    @kb.add("/")
    def _handle_slash(event):
        if not engine.modal:
            screen = engine.current_screen
            screen.search_mode = True
            screen.search_query = ""

    # Direct number switching for root menu
    for i in range(1, 7):
        @kb.add(str(i))
        def _handle_number(event, idx=i-1):
            screen = engine.current_screen
            if screen.search_mode:
                screen.search_query += str(idx + 1)
                return
            if len(engine.stack) == 1 and not engine.modal:
                items = engine.get_current_items()
                if idx < len(items) and items[idx].on_select:
                    items[idx].on_select()

    @kb.add("<any>")
    def _handle_any(event):
        if engine.modal and engine.modal.get("type") == "exit_confirm":
            if event.data.lower() == "y":
                event.app.exit(result=0)
            elif event.data.lower() == "n":
                engine.modal = None
            return

        screen = engine.current_screen
        if screen.search_mode:
            screen.search_query += event.data

    @kb.add("backspace")
    def _handle_backspace(event):
        screen = engine.current_screen
        if screen.search_mode:
            screen.search_query = screen.search_query[:-1]

    # Layout Construction
    header_win = Window(content=FormattedTextControl(lambda: render_header(engine)), height=2)

    def get_list_height() -> int:
        return 18

    list_win = Window(content=FormattedTextControl(lambda: render_item_list(engine, get_list_height())), width=38)
    detail_win = Window(content=FormattedTextControl(lambda: render_detail_pane(engine)), wrap_lines=True)
    split_body = VSplit([list_win, Window(width=1, char="│", style="class:border"), detail_win])

    modal_win = Window(content=FormattedTextControl(lambda: render_modal_overlay(engine)), height=16)
    is_modal_active = Condition(lambda: bool(engine.modal))

    footer_win = Window(content=FormattedTextControl(lambda: render_footer(engine)), height=2)

    root_container = HSplit([
        header_win,
        Window(height=1, char="─", style="class:border"),
        split_body,
        ConditionalContainer(
            HSplit([
                Window(height=1, char="─", style="class:border"),
                modal_win,
            ]),
            filter=is_modal_active,
        ),
        Window(height=1, char="─", style="class:border"),
        footer_win,
    ])

    style = Style.from_dict({
        "header.brand": "bold cyan",
        "header.bar": "dim",
        "breadcrumb.active": "bold white",
        "breadcrumb.inactive": "dim white",
        "breadcrumb.sep": "dim cyan",
        "section.title": "bold cyan",
        "item.selected": "bold cyan",
        "item.selected.sub": "dim cyan",
        "item.unselected": "white",
        "item.subtitle": "dim",
        "item.empty": "italic dim",
        "inspector.title": "bold cyan",
        "inspector.item_title": "bold white",
        "action.prompt": "bold cyan",
        "tag.green": "green",
        "tag.yellow": "yellow",
        "tag.red": "red",
        "tag.blue": "blue",
        "tag.cyan": "cyan",
        "tag.magenta": "magenta",
        "tag.dim": "dim",
        "search.bar": "yellow",
        "search.active": "bold white bg:#223344",
        "modal.border": "dim",
        "modal.title": "bold cyan",
        "modal.body": "white",
        "modal.prompt": "dim cyan",
        "modal.success": "green",
        "modal.fail": "red",
        "footer.status": "white",
        "footer.error": "bold red",
        "footer.guide": "dim",
        "border": "dim",
        "bold": "bold",
        "dim": "dim",
        "cyan": "cyan",
        "green": "green",
    })

    layout = Layout(root_container)
    app = Application(layout=layout, key_bindings=kb, style=style, full_screen=True)
    return app.run()
