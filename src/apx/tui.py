# SPDX-License-Identifier: MPL-2.0
"""APX Interactive Terminal User Interface (TUI).

Provides a keyboard-first, responsive, and polished terminal interface for
browsing actions, inspecting resources, running operations, testing policy,
and monitoring hardware capabilities.
"""
from __future__ import annotations

import json
import sys
import time
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
from .settings import get_all_settings
from . import __version__

# Navigation Tabs
TABS = [
    ("overview", "1. Overview"),
    ("actions", "2. Actions"),
    ("resources", "3. Resources"),
    ("providers", "4. Providers"),
    ("work", "5. Work"),
    ("policy", "6. Identity & Policy"),
    ("nodes", "7. Nodes"),
    ("settings", "8. Settings"),
]


@dataclass
class ListItem:
    id: str
    title: str
    subtitle: str = ""
    tag: str = ""
    tag_style: str = "cyan"
    data: dict[str, Any] = field(default_factory=dict)


class TUIState:
    def __init__(self, cloud: APX, actor: str | None = None):
        self.cloud = cloud
        self.actor = actor or cloud.actors.resolve_default()
        self.active_tab_idx: int = 0
        self.selected_idx: int = 0
        self.scroll_offset: int = 0
        self.filter_query: str = ""
        self.search_mode: bool = False
        self.status_message: str = "Ready. Use ↑/↓ to navigate, Enter to select, / to search, q to quit."
        self.status_is_error: bool = False
        self.modal: dict[str, Any] | None = None
        self.cached_hardware: dict[str, Any] = {}
        self.refresh_cache()

    @property
    def active_tab(self) -> str:
        return TABS[self.active_tab_idx][0]

    def refresh_cache(self) -> None:
        try:
            self.cached_hardware = inspect_hardware()
        except Exception:
            self.cached_hardware = {}

    def get_items(self) -> list[ListItem]:
        tab = self.active_tab
        items: list[ListItem] = []

        if tab == "overview":
            items = [
                ListItem("stat_actions", f"Action Catalog ({len(self.cloud.actions.list())} actions)", "Browse and execute standardized actions", "CATALOG", "green"),
                ListItem("stat_resources", f"Discovered Resources ({len(self.cloud.resources())} resources)", "Hosts, projects, databases, services", "GRAPH", "blue"),
                ListItem("stat_providers", f"Action Providers ({len(self.cloud.providers)} providers)", "Connected native and remote providers", "ONLINE", "cyan"),
                ListItem("stat_hardware", f"Compute Tier: {self.cached_hardware.get('compute_tier', 'unknown')}", f"CPU: {self.cached_hardware.get('cpu', {}).get('model', 'Unknown')}", "HARDWARE", "yellow"),
                ListItem("act_conformance", "Run Protocol Conformance Check", "Validate APX 0.1 protocol adherence", "TEST", "magenta"),
                ListItem("act_fleet", "Run Fleet Health Probe", "Check reachability and status across all hosts", "FLEET", "cyan"),
            ]
        elif tab == "actions":
            for action in self.cloud.actions.list():
                risk = getattr(action, "risk", "read") or "read"
                tag_style = "green" if risk == "read" else ("red" if risk in {"destructive", "shutdown"} else "yellow")
                items.append(ListItem(
                    id=action.name,
                    title=action.name,
                    subtitle=action.description or "",
                    tag=risk.upper(),
                    tag_style=tag_style,
                    data=action.to_dict() if hasattr(action, "to_dict") else {"name": action.name}
                ))
        elif tab == "resources":
            for res in self.cloud.resources():
                kind = getattr(res, "kind", "resource")
                items.append(ListItem(
                    id=res.id,
                    title=f"{res.id}",
                    subtitle=f"{res.name} (Kind: {kind})",
                    tag=kind.upper(),
                    tag_style="blue",
                    data=res.to_dict() if hasattr(res, "to_dict") else {"id": res.id}
                ))
        elif tab == "providers":
            for pid, prov in self.cloud.providers.items():
                name = getattr(prov, "name", pid)
                actions_count = len(getattr(prov, "actions", [])) if hasattr(prov, "actions") else 0
                items.append(ListItem(
                    id=pid,
                    title=f"{name} ({pid})",
                    subtitle=f"{actions_count} exposed actions",
                    tag="ONLINE",
                    tag_style="green",
                    data={"id": pid, "name": name, "actions_count": actions_count}
                ))
        elif tab == "work":
            missions = self.cloud.missions.list()
            if not missions:
                items.append(ListItem("empty_work", "No active missions configured", "Use 'apx mission create' to declare desired outcomes", "INFO", "dim"))
            else:
                for m in missions:
                    status = m.get("status", "open")
                    tag_style = "green" if status == "completed" else "yellow"
                    items.append(ListItem(
                        id=m["id"],
                        title=f"{m.get('title', m['id'])}",
                        subtitle=m.get("rationale", ""),
                        tag=status.upper(),
                        tag_style=tag_style,
                        data=m
                    ))
        elif tab == "policy":
            items.append(ListItem("active_actor", f"Current Actor: {self.actor}", "Default acting identity for APX operations", "ACTOR", "cyan"))
            actors = self.cloud.actors.list()
            for a in actors:
                roles = getattr(a, "roles", [])
                items.append(ListItem(
                    id=a.id,
                    title=f"Actor: {a.id}",
                    subtitle=f"Roles: {', '.join(roles) if roles else 'none'}",
                    tag="ROLE",
                    tag_style="yellow",
                    data=a.to_dict() if hasattr(a, "to_dict") else {"id": a.id}
                ))
            grants = self.cloud.grants.list()
            for g in grants:
                items.append(ListItem(
                    id=g.get("grant_id", "grant"),
                    title=f"Grant: {g.get('grant_id')}",
                    subtitle=f"To: {g.get('actor')} for {g.get('action')}",
                    tag="GRANT",
                    tag_style="magenta",
                    data=g
                ))
        elif tab == "nodes":
            hw = self.cached_hardware
            items = [
                ListItem("node_tier", f"Compute Tier: {hw.get('compute_tier', 'unknown')}", "Determined local compute capability rating", "TIER", "cyan"),
                ListItem("node_cpu", f"CPU: {hw.get('cpu', {}).get('model', 'Unknown')}", f"Cores: {hw.get('cpu', {}).get('cores', 1)}, Arch: {hw.get('cpu', {}).get('architecture', '')}", "CPU", "yellow"),
                ListItem("node_mem", f"Memory: {hw.get('memory', {}).get('total_gb', 0)} GB Total", f"Available: {hw.get('memory', {}).get('available_gb', 0)} GB", "RAM", "green"),
                ListItem("node_acc", "Accelerators & AI Engine", f"Metal: {hw.get('accelerators', {}).get('metal')} | ANE: {hw.get('accelerators', {}).get('neural_engine')} | CUDA: {hw.get('accelerators', {}).get('cuda')}", "ACCEL", "magenta"),
                ListItem("node_storage", f"Storage: {hw.get('storage', {}).get('free_gb', 0)} GB Free", f"Total: {hw.get('storage', {}).get('total_gb', 0)} GB ({hw.get('storage', {}).get('percent_free', 0)}% free)", "DISK", "blue"),
            ]
        elif tab == "settings":
            all_s = get_all_settings(self.cloud.config_path)
            items = [
                ListItem("set_version", f"APX Version: {__version__}", "Universal Action Protocol & Capability Fabric", "CORE", "cyan"),
                ListItem("set_config", f"Config Path: {all_s.get('paths', {}).get('config_path')}", f"Status: {'Exists' if all_s.get('paths', {}).get('config_exists') else 'Not Found'}", "PATH", "yellow"),
                ListItem("set_home", f"APX Home: {all_s.get('paths', {}).get('apx_home')}", "Standard configuration directory", "PATH", "yellow"),
                ListItem("set_node", f"Node Name: {all_s.get('node', {}).get('name', 'local')}", f"Default Actor: {all_s.get('node', {}).get('default_actor', self.actor)}", "NODE", "green"),
            ]

        # Apply search filter if present
        if self.filter_query.strip():
            q = self.filter_query.lower()
            items = [item for item in items if q in item.title.lower() or q in item.subtitle.lower() or q in item.id.lower()]

        return items


def render_header(state: TUIState) -> FormattedText:
    tokens = []
    tokens.append(("class:header.title", " ⚡ APX PROTOCOL & CAPABILITY FABRIC "))
    tokens.append(("class:header.badge", f" [Node: local | {state.cached_hardware.get('compute_tier', 'active')}] "))
    tokens.append(("class:header.actor", f" [Actor: {state.actor}] \n"))

    # Tab navigation bar
    for idx, (tab_id, tab_label) in enumerate(TABS):
        if idx == state.active_tab_idx:
            tokens.append(("class:tab.active", f" {tab_label} "))
        else:
            tokens.append(("class:tab.inactive", f" {tab_label} "))
        tokens.append(("", " "))
    tokens.append(("", "\n"))
    return tokens


def render_item_list(state: TUIState, height: int) -> FormattedText:
    items = state.get_items()
    tokens = []

    if state.search_mode:
        tokens.append(("class:search.active", f" 🔍 Filter: {state.filter_query}_ (Press Enter to apply, Esc to clear)\n"))
    elif state.filter_query:
        tokens.append(("class:search.bar", f" 🔍 Filter: {state.filter_query} (Press / to edit, Esc to clear)\n"))
    else:
        tokens.append(("class:section.title", f" ── {TABS[state.active_tab_idx][1]} ({len(items)} items) ──\n"))

    if not items:
        tokens.append(("class:item.empty", "\n   (No items match current view/filter)\n"))
        return tokens

    # Ensure selected index is within bounds
    if state.selected_idx >= len(items):
        state.selected_idx = max(0, len(items) - 1)

    max_visible = max(5, height - 3)
    # Adjust scroll offset
    if state.selected_idx < state.scroll_offset:
        state.scroll_offset = state.selected_idx
    elif state.selected_idx >= state.scroll_offset + max_visible:
        state.scroll_offset = state.selected_idx - max_visible + 1

    visible_items = items[state.scroll_offset : state.scroll_offset + max_visible]

    for idx, item in enumerate(visible_items):
        actual_idx = state.scroll_offset + idx
        is_selected = actual_idx == state.selected_idx

        prefix = " ▶ " if is_selected else "   "
        style_base = "class:item.selected" if is_selected else "class:item.unselected"

        tokens.append((style_base, prefix))
        tag_style = f"class:tag.{item.tag_style}" if not is_selected else style_base
        tokens.append((tag_style, f"[{item.tag}] "))
        tokens.append((style_base, f"{item.title}"))

        if item.subtitle:
            sub_style = "class:item.selected.sub" if is_selected else "class:item.subtitle"
            tokens.append((sub_style, f" — {item.subtitle}"))
        tokens.append(("", "\n"))

    return tokens


def render_inspector_pane(state: TUIState) -> FormattedText:
    tokens = []
    tokens.append(("class:inspector.title", " ── Inspector & Details ──\n\n"))

    items = state.get_items()
    if not items or state.selected_idx >= len(items):
        tokens.append(("class:dim", " Select an item to inspect details.\n"))
        return tokens

    item = items[state.selected_idx]
    tokens.append(("class:inspector.item_title", f" Item: {item.title}\n"))
    tokens.append(("class:dim", f" ID:   {item.id}\n"))
    tokens.append(("class:dim", f" Tag:  {item.tag}\n\n"))

    if state.active_tab == "actions":
        action = state.cloud.actions.get(item.id)
        if action:
            tokens.append(("class:bold", f" Description:\n"))
            tokens.append(("", f"  {action.description or 'No description provided.'}\n\n"))
            tokens.append(("class:bold", f" Execution Parameters:\n"))
            tokens.append(("", f"  • Risk Level:     {action.risk}\n"))
            tokens.append(("", f"  • Confirmation:   {action.confirmation}\n"))
            tokens.append(("", f"  • Read Only:      {action.read_only}\n"))
            tokens.append(("", f"  • Destructive:    {action.destructive}\n"))
            tokens.append(("", f"  • Idempotent:     {action._idempotent()}\n"))
            tokens.append(("", f"  • Provenance:     {action.provenance}\n\n"))

            props = action.schema.get("properties", {})
            if props:
                tokens.append(("class:bold", " Expected Input Schema:\n"))
                for k, v in props.items():
                    req = " (required)" if k in action.schema.get("required", []) else ""
                    tokens.append(("class:cyan", f"  • {k}"))
                    tokens.append(("", f": {v.get('type', 'any')}{req}\n"))
                    if v.get("description"):
                        tokens.append(("class:dim", f"    {v.get('description')}\n"))
            else:
                tokens.append(("class:dim", " Input Schema: Zero-argument action\n"))

            tokens.append(("\nclass:action.prompt", " [Press Enter to Execute this Action]\n"))

    elif state.active_tab == "resources":
        tokens.append(("class:bold", " Resource Attributes:\n"))
        tokens.append(("", f" {json.dumps(item.data, indent=2)}\n\n"))
        tokens.append(("class:bold", " Relationships:\n"))
        rels = [r for r in state.cloud.relationships() if r.source == item.id or r.target == item.id]
        if rels:
            for r in rels:
                tokens.append(("class:cyan", f"  • ({r.source}) ──[{r.relation}]──► ({r.target})\n"))
        else:
            tokens.append(("class:dim", "  No explicit relationships configured.\n"))

    elif state.active_tab == "nodes":
        tokens.append(("class:bold", " On-Device Compute Specifications:\n"))
        tokens.append(("", f" {json.dumps(state.cached_hardware, indent=2)}\n"))

    elif state.active_tab == "policy":
        tokens.append(("class:bold", " Identity & Role Context:\n"))
        tokens.append(("", f" {json.dumps(item.data, indent=2)}\n\n"))
        tokens.append(("class:dim", " Use 'apx policy explain <actor> <action>' for authorization proof.\n"))

    else:
        if item.data:
            tokens.append(("class:bold", " Details:\n"))
            tokens.append(("", f" {json.dumps(item.data, indent=2)}\n"))
        else:
            tokens.append(("class:dim", f" {item.subtitle}\n"))

    return tokens


def render_modal_overlay(state: TUIState) -> FormattedText:
    if not state.modal:
        return []
    modal = state.modal
    m_type = modal.get("type")
    tokens = []

    tokens.append(("class:modal.border", "╔══════════════════════════════════════════════════════════════════════╗\n"))
    tokens.append(("class:modal.title", f"║  {modal.get('title', 'Action Execution').center(66)}  ║\n"))
    tokens.append(("class:modal.border", "╠══════════════════════════════════════════════════════════════════════╣\n"))

    if m_type == "action_confirm":
        action_name = modal.get("action_name", "")
        destructive = modal.get("destructive", False)
        tokens.append(("class:modal.body", f"║  Action: {action_name.ljust(58)}║\n"))
        if destructive:
            tokens.append(("class:modal.warn", "║  ⚠️  WARNING: This is a DESTRUCTIVE action!                          ║\n"))
        tokens.append(("class:modal.body", "║                                                                      ║\n"))
        tokens.append(("class:modal.prompt", "║  Press [Enter] to Confirm & Execute, or [Esc] to Cancel             ║\n"))

    elif m_type == "action_result":
        ok = modal.get("ok", False)
        action_name = modal.get("action_name", "")
        duration = modal.get("duration", 0)
        status_text = "✓ SUCCESS" if ok else "✗ FAILED"
        status_style = "class:modal.success" if ok else "class:modal.fail"

        tokens.append((status_style, f"║  Status: {status_text} (Time: {duration:.2f}s)".ljust(70) + "║\n"))
        tokens.append(("class:modal.body", f"║  Action: {action_name}".ljust(70) + "║\n"))
        tokens.append(("class:modal.border", "╟──────────────────────────────────────────────────────────────────────╢\n"))

        res_str = modal.get("result_str", "")
        lines = res_str.splitlines()[:12]
        for line in lines:
            line_clean = line[:66].ljust(66)
            tokens.append(("class:modal.body", f"║  {line_clean}  ║\n"))
        tokens.append(("class:modal.border", "╟──────────────────────────────────────────────────────────────────────╢\n"))
        tokens.append(("class:modal.prompt", "║  Press [Enter] or [Esc] to Close                                     ║\n"))

    elif m_type == "help":
        tokens.append(("class:modal.body", "║  Keyboard Navigation:                                                ║\n"))
        tokens.append(("class:modal.body", "║   • ↑ / ↓ or k / j     : Move selection up and down                  ║\n"))
        tokens.append(("class:modal.body", "║   • Tab / Shift-Tab    : Switch tabs (or press 1-8)                  ║\n"))
        tokens.append(("class:modal.body", "║   • Enter              : Execute action / View details               ║\n"))
        tokens.append(("class:modal.body", "║   • /                  : Search & filter items                       ║\n"))
        tokens.append(("class:modal.body", "║   • Esc                : Cancel / Back / Close modal                 ║\n"))
        tokens.append(("class:modal.body", "║   • q / Ctrl-C         : Quit APX                                    ║\n"))
        tokens.append(("class:modal.border", "╟──────────────────────────────────────────────────────────────────────╢\n"))
        tokens.append(("class:modal.prompt", "║  Press [Enter] or [Esc] to return                                    ║\n"))

    tokens.append(("class:modal.border", "╚══════════════════════════════════════════════════════════════════════╝\n"))
    return tokens


def render_footer(state: TUIState) -> FormattedText:
    tokens = []
    # Status / Alert line
    msg_style = "class:footer.error" if state.status_is_error else "class:footer.status"
    tokens.append((msg_style, f" {state.status_message}\n"))

    # Keybinding guide
    guide = " [↑/↓] Navigate  •  [Enter] Select/Run  •  [/] Filter  •  [Tab] Next Tab  •  [Esc] Back  •  [?] Help  •  [q] Quit "
    tokens.append(("class:footer.guide", guide))
    return tokens


def run_tui(config_path: Path | str | None = None, actor: str | None = None) -> int:
    """Entry point for the interactive APX Terminal User Interface."""
    cloud = APX(config_path, plugins=True)
    state = TUIState(cloud=cloud, actor=actor)

    kb = KeyBindings()

    @kb.add("q")
    def _exit(event):
        if state.search_mode:
            state.filter_query += "q"
            return
        if state.modal:
            state.modal = None
            return
        event.app.exit(result=0)

    @kb.add("c-c")
    def _ctrl_c(event):
        event.app.exit(result=0)

    @kb.add("?")
    def _help_question(event):
        if state.search_mode:
            state.filter_query += "?"
            return
        state.modal = {"type": "help", "title": "APX TUI Keyboard Guide"}

    @kb.add("tab")
    def _next_tab(event):
        if state.modal:
            return
        state.active_tab_idx = (state.active_tab_idx + 1) % len(TABS)
        state.selected_idx = 0
        state.scroll_offset = 0

    @kb.add("s-tab")
    def _prev_tab(event):
        if state.modal:
            return
        state.active_tab_idx = (state.active_tab_idx - 1) % len(TABS)
        state.selected_idx = 0
        state.scroll_offset = 0

    # Number keys for direct tab switching
    for i in range(1, 9):
        @kb.add(str(i))
        def _switch_tab_num(event, idx=i-1):
            if state.search_mode:
                state.filter_query += str(idx + 1)
                return
            if not state.modal:
                state.active_tab_idx = idx
                state.selected_idx = 0
                state.scroll_offset = 0

    @kb.add("up")
    @kb.add("k")
    def _up(event):
        if state.modal:
            return
        if state.selected_idx > 0:
            state.selected_idx -= 1

    @kb.add("down")
    @kb.add("j")
    def _down(event):
        if state.modal:
            return
        items = state.get_items()
        if state.selected_idx < len(items) - 1:
            state.selected_idx += 1

    @kb.add("/")
    def _start_search(event):
        if not state.modal:
            state.search_mode = True
            state.filter_query = ""

    @kb.add("escape")
    def _cancel(event):
        if state.modal:
            state.modal = None
            return
        if state.search_mode:
            state.search_mode = False
            state.filter_query = ""
            return
        if state.filter_query:
            state.filter_query = ""
            return

    @kb.add("enter")
    def _enter(event):
        if state.search_mode:
            state.search_mode = False
            return

        if state.modal:
            m_type = state.modal.get("type")
            if m_type == "action_confirm":
                # Execute action
                action_name = state.modal["action_name"]
                t0 = time.time()
                try:
                    result = state.cloud.run(action_name, actor=state.actor)
                    dt = time.time() - t0
                    res_dict = result.to_dict()
                    state.modal = {
                        "type": "action_result",
                        "title": f"Execution Result: {action_name}",
                        "action_name": action_name,
                        "ok": result.ok,
                        "duration": dt,
                        "result_str": json.dumps(res_dict.get("result") or res_dict.get("error") or res_dict, indent=2),
                    }
                    state.status_message = f"Executed {action_name} in {dt:.2f}s ({'OK' if result.ok else 'Failed'})"
                    state.status_is_error = not result.ok
                except Exception as ex:
                    state.modal = {
                        "type": "action_result",
                        "title": f"Execution Error: {action_name}",
                        "action_name": action_name,
                        "ok": False,
                        "duration": 0,
                        "result_str": str(ex),
                    }
                    state.status_message = f"Error: {ex}"
                    state.status_is_error = True
                return
            elif m_type == "action_result" or m_type == "help":
                state.modal = None
                return

        # Top level enter
        items = state.get_items()
        if not items or state.selected_idx >= len(items):
            return

        item = items[state.selected_idx]

        if state.active_tab == "actions":
            action = state.cloud.actions.get(item.id)
            if action:
                # Open confirmation / run modal
                state.modal = {
                    "type": "action_confirm",
                    "title": f"Execute Action: {action.name}",
                    "action_name": action.name,
                    "destructive": action.destructive,
                }
        elif state.active_tab == "overview":
            if item.id == "act_conformance":
                from .conformance import check_conformance
                conf = check_conformance(state.cloud)
                state.modal = {
                    "type": "action_result",
                    "title": "APX 0.1 Protocol Conformance",
                    "action_name": "protocol.conformance",
                    "ok": conf["ok"],
                    "duration": 0.05,
                    "result_str": json.dumps(conf, indent=2),
                }
            elif item.id == "act_fleet":
                res = state.cloud.run("fleet.health", actor=state.actor)
                state.modal = {
                    "type": "action_result",
                    "title": "Fleet Health Probe",
                    "action_name": "fleet.health",
                    "ok": res.ok,
                    "duration": 0.1,
                    "result_str": json.dumps(res.result or res.to_dict(), indent=2),
                }

    # Catch-all for typing inside search mode
    @kb.add("<any>")
    def _any_key(event):
        if state.search_mode:
            state.filter_query += event.data

    @kb.add("backspace")
    def _backspace(event):
        if state.search_mode:
            state.filter_query = state.filter_query[:-1]

    # Layout Containers
    header_window = Window(content=FormattedTextControl(lambda: render_header(state)), height=3)

    def get_list_height() -> int:
        return 18

    list_window = Window(content=FormattedTextControl(lambda: render_item_list(state, get_list_height())), width=45)
    inspector_window = Window(content=FormattedTextControl(lambda: render_inspector_pane(state)), wrap_lines=True)
    split_body = VSplit([list_window, Window(width=1, char="│", style="class:border"), inspector_window])

    modal_window = Window(content=FormattedTextControl(lambda: render_modal_overlay(state)), height=16)
    is_modal_active = Condition(lambda: bool(state.modal))

    footer_window = Window(content=FormattedTextControl(lambda: render_footer(state)), height=2)

    root_container = HSplit([
        header_window,
        Window(height=1, char="─", style="class:border"),
        split_body,
        ConditionalContainer(
            HSplit([
                Window(height=1, char="─", style="class:border"),
                modal_window,
            ]),
            filter=is_modal_active,
        ),
        Window(height=1, char="─", style="class:border"),
        footer_window,
    ])

    style = Style.from_dict({
        "header.title": "bold white bg:#003366",
        "header.badge": "bold cyan bg:#112233",
        "header.actor": "bold yellow bg:#112233",
        "tab.active": "bold black bg:#00d7ff",
        "tab.inactive": "bold white bg:#223344",
        "section.title": "bold cyan",
        "item.selected": "bold black bg:#00d7ff",
        "item.selected.sub": "italic black bg:#00d7ff",
        "item.unselected": "white",
        "item.subtitle": "dim",
        "item.empty": "italic dim",
        "inspector.title": "bold cyan",
        "inspector.item_title": "bold yellow",
        "tag.green": "bold green",
        "tag.yellow": "bold yellow",
        "tag.red": "bold red",
        "tag.blue": "bold blue",
        "tag.cyan": "bold cyan",
        "tag.magenta": "bold magenta",
        "tag.dim": "dim",
        "search.bar": "bold yellow",
        "search.active": "bold white bg:#334455",
        "modal.border": "bold cyan",
        "modal.title": "bold white bg:#004488",
        "modal.body": "white bg:#112233",
        "modal.warn": "bold yellow bg:#442200",
        "modal.prompt": "bold cyan bg:#112233",
        "modal.success": "bold green bg:#003311",
        "modal.fail": "bold red bg:#330000",
        "footer.status": "bold white bg:#1a1a2e",
        "footer.error": "bold red bg:#2e1a1a",
        "footer.guide": "dim white bg:#111122",
        "border": "#445566",
        "bold": "bold",
        "dim": "dim",
        "cyan": "cyan",
    })

    layout = Layout(root_container)
    app = Application(layout=layout, key_bindings=kb, style=style, full_screen=True)
    return app.run()
