# SPDX-License-Identifier: MPL-2.0
"""`apx menu` -- an interactive terminal UI over the same deterministic Action
runtime the scripted CLI uses. Arrow keys / j,k to move, Enter to select, Esc
to go back (or quit at the root), `/` to filter the current list. Nothing here
bypasses APX authorization: every action still goes through cloud.run(), with
the same confirmation/--yes-equivalent gate the scripted CLI applies.

Deliberately stdlib-only (curses) -- no new dependency for a CLI whose whole
premise is a small, auditable, always-available surface. The visual language
(a single accent color, a connector glyph tying a title to its list, a filled
marker on the selected row instead of a block of reverse video, dim chrome
everywhere else) is deliberately modeled on `@clack/prompts` -- the Node.js
prompt library OpenClaw's own onboarding wizard is built on -- adapted to
curses rather than ported, since there is no line-for-line equivalent between
a React/Ink-style renderer and a curses redraw loop.
"""
from __future__ import annotations

import curses
import json
from typing import Any, Callable

from .cloud import APX

ESC = 27
ENTER = (10, 13)
BACKSPACE = (curses.KEY_BACKSPACE, 127, 8) if hasattr(curses, "KEY_BACKSPACE") else (127, 8)

# clack's palette is one accent color used consistently for anything "active"
# (the current step marker, the selected row, the prompt caret) plus dimmed
# text for everything structural -- not a wall of different colors. Falls back
# to no color at all on a terminal that doesn't support it (start_color()
# raising is handled in TUI.__init__), which is why every draw call still
# works with attr=0 as the default.
_ACCENT = 1   # cyan: active/selected
_GOOD = 2     # green: success / non-destructive confirm
_WARN = 3     # yellow: destructive confirm prompt
_DIM = 4      # the connector line, hints, unselected chrome


class Quit(Exception):
    """Raised to unwind the whole menu, not just one screen."""


class TUI:
    def __init__(self, stdscr: "curses._CursesWindow", cloud: APX, actor: str):
        self.stdscr = stdscr
        self.cloud = cloud
        self.actor = actor
        self.color = False
        curses.curs_set(0)
        try:
            curses.use_default_colors()
            curses.init_pair(_ACCENT, curses.COLOR_CYAN, -1)
            curses.init_pair(_GOOD, curses.COLOR_GREEN, -1)
            curses.init_pair(_WARN, curses.COLOR_YELLOW, -1)
            curses.init_pair(_DIM, curses.COLOR_WHITE, -1)  # dimmed via A_DIM, not a gray color pair
            self.color = True
        except curses.error: pass
        stdscr.keypad(True)

    def _attr(self, pair: int, extra: int = 0) -> int:
        return (curses.color_pair(pair) | extra) if self.color else extra

    # ------------------------------------------------------------------ primitives

    def choose(self, title: str, items: list[tuple[str, str]], footer: str = "") -> int | None:
        """items: (label, hint) pairs. Returns the selected index into `items`, or None on Esc/q."""
        query, idx, typing = "", 0, False
        default_footer = footer or "↑/↓ move   enter select   / filter   esc back"
        while True:
            filtered = [i for i, (label, _) in enumerate(items) if query.lower() in label.lower()]
            idx = min(idx, max(0, len(filtered) - 1))
            self._draw_list(title, items, filtered, idx, query, typing, default_footer)
            key = self.stdscr.getch()
            if typing:
                if key in ENTER or key == ESC: typing = False
                elif key in BACKSPACE: query = query[:-1]
                elif 32 <= key < 127: query += chr(key)
                continue
            if key in (curses.KEY_UP, ord("k")): idx = max(0, idx - 1)
            elif key in (curses.KEY_DOWN, ord("j")): idx = min(len(filtered) - 1, idx + 1) if filtered else 0
            elif key in ENTER:
                if filtered: return filtered[idx]
            elif key == ord("/"): typing = True
            elif key in (ord("q"), ord("Q"), ESC):
                if query: query, idx = "", 0
                else: return None

    def _draw_list(self, title, items, filtered, idx, query, typing, footer) -> None:
        # clack's signature shape: a filled diamond marks the active step, a
        # vertical bar connects it down to its list, and only the selected row
        # carries color -- everything else stays plain/dim so the one thing
        # that changed (your position) is the only thing that draws the eye.
        stdscr = self.stdscr
        stdscr.erase()
        height, width = stdscr.getmaxyx()
        stdscr.addnstr(0, 0, "◆ ", width - 1, self._attr(_ACCENT, curses.A_BOLD))
        stdscr.addnstr(0, 2, title, width - 3, curses.A_BOLD)
        top = 2
        visible = height - top - 2
        start = max(0, idx - visible + 1) if idx >= visible else 0
        for row, pos in enumerate(filtered[start:start + visible]):
            label, hint = items[pos]
            selected = (start + row) == idx
            stdscr.addnstr(top + row, 0, "│", 1, self._attr(_DIM, curses.A_DIM))
            marker = "❯" if selected else " "
            stdscr.addnstr(top + row, 2, marker, 1, self._attr(_ACCENT, curses.A_BOLD))
            label_attr = self._attr(_ACCENT, curses.A_BOLD) if selected else curses.A_NORMAL
            stdscr.addnstr(top + row, 4, label, width - 5, label_attr)
            if hint:
                hint_col = 4 + len(label) + 2
                if hint_col < width - 1: stdscr.addnstr(top + row, hint_col, hint, width - hint_col - 1, curses.A_DIM)
        if not filtered:
            stdscr.addnstr(top, 4, "(no matches)", width - 5, curses.A_DIM)
        stdscr.addnstr(top + visible, 0, "└", 1, self._attr(_DIM, curses.A_DIM))
        status = f"/{query}" if typing or query else footer
        stdscr.addnstr(height - 1, 0, status, width - 1, curses.A_DIM)
        stdscr.refresh()

    def message(self, lines: list[str], title: str = "") -> None:
        stdscr = self.stdscr
        stdscr.erase()
        height, width = stdscr.getmaxyx()
        row = 0
        if title:
            stdscr.addnstr(row, 0, "◆ ", width - 1, self._attr(_ACCENT, curses.A_BOLD))
            stdscr.addnstr(row, 2, title, width - 3, curses.A_BOLD); row += 2
        for line in lines[: height - row - 2]:
            stdscr.addnstr(row, 0, "│", 1, self._attr(_DIM, curses.A_DIM))
            stdscr.addnstr(row, 2, line, width - 3); row += 1
        stdscr.addnstr(row, 0, "└", 1, self._attr(_DIM, curses.A_DIM))
        stdscr.addnstr(height - 1, 0, "any key to continue", width - 1, curses.A_DIM)
        stdscr.refresh()
        stdscr.getch()

    def confirm(self, prompt: str, *, danger: bool = False) -> bool:
        stdscr = self.stdscr
        stdscr.erase()
        height, width = stdscr.getmaxyx()
        pair = _WARN if danger else _GOOD
        stdscr.addnstr(height // 2, 0, "◆ ", width - 1, self._attr(pair, curses.A_BOLD))
        stdscr.addnstr(height // 2, 2, f"{prompt}", width - 3, curses.A_BOLD)
        stdscr.addnstr(height // 2 + 1, 2, "  [y] yes    [N] no", width - 3, curses.A_DIM)
        stdscr.refresh()
        return stdscr.getch() in (ord("y"), ord("Y"))

    def read_line(self, prompt: str, default: str = "") -> str | None:
        stdscr = self.stdscr
        value = default
        curses.curs_set(1)
        try:
            while True:
                height, width = stdscr.getmaxyx()
                stdscr.erase()
                stdscr.addnstr(height // 2, 0, "◆ ", width - 1, self._attr(_ACCENT, curses.A_BOLD))
                stdscr.addnstr(height // 2, 2, f"{prompt}", width - 3, curses.A_BOLD)
                stdscr.addnstr(height // 2 + 1, 2, f"│ {value}", width - 3, self._attr(_ACCENT))
                stdscr.refresh()
                key = stdscr.getch()
                if key in ENTER: return value
                if key == ESC: return None
                if key in BACKSPACE: value = value[:-1]
                elif 32 <= key < 127: value += chr(key)
        finally:
            curses.curs_set(0)

    # ------------------------------------------------------------------ action execution

    def run_action(self, name: str, **inputs: Any):
        """Mirrors the scripted CLI's `run`/`blueprint apply`/etc. gate: destructive or
        confirmation-required actions get an explicit y/n before anything executes."""
        action = self.cloud.actions.get(name)
        confirmation = None
        if action.destructive and not self.confirm(f"{name} is destructive. Proceed?", danger=True):
            return None
        if action.confirmation != "none":
            confirmation = {"level": action.confirmation, "confirmed": True, "authorization_id": f"tui:{name}"}
        return self.cloud.run(name, actor=self.actor, confirmation=confirmation, **inputs)

    def show_result(self, result, title: str = "") -> None:
        if result is None:  # user declined the confirm prompt
            return
        if not result.ok:
            detail = result.error.to_dict() if result.error else {"error": "unknown error"}
            self.message(_format_lines(detail), title=title or f"{result.action} failed")
            return
        self.message(_format_lines(result.result), title=title or result.action)

    # ------------------------------------------------------------------ screens

    def root(self, start_screen: str | None = None) -> None:
        items = [
            ("Doctor", "run diagnostics"),
            ("Servers", "configured Hosts: status, services"),
            ("Credentials", "API keys, tokens -- add/inspect (values never shown)"),
            ("Standing Agents", "list, inspect, start/stop the loop"),
            ("Blueprints", "versioned action graphs"),
            ("Grants", "delegated authority"),
            ("Search", "deterministic local search"),
            ("System state", "normal / incident / lockdown"),
            ("Plugins", "loaded plugin health"),
            ("Command palette", "jump straight to any registered Action"),
        ]
        screens: list[Callable[[], None]] = [
            self.screen_doctor, self.screen_servers, self.screen_credentials, self.screen_agents,
            self.screen_blueprints, self.screen_grants, self.screen_search,
            self.screen_state, self.screen_plugins, self.screen_palette,
        ]
        by_name = {"doctor": 0, "servers": 1, "credentials": 2, "agents": 3, "blueprints": 4,
                   "grants": 5, "search": 6, "state": 7, "plugins": 8, "palette": 9}
        if start_screen in by_name:
            screens[by_name[start_screen]]()  # one-shot jump (e.g. `apx --add-keys`); falls through to the normal root loop after
        while True:
            choice = self.choose("apx", items, footer="↑/↓ move   enter select   / filter   esc/q quit")
            if choice is None: return
            screens[choice]()

    def screen_doctor(self) -> None:
        from .doctor import diagnose
        result = diagnose(self.cloud.config_path if hasattr(self.cloud, "config_path") else None)
        self.message(_format_lines(result), title="doctor")

    def screen_credentials(self) -> None:
        while True:
            ids = sorted(self.cloud.credentials.references) if hasattr(self.cloud, "credentials") else []
            hints = []
            for cred_id in ids:
                outcome = self.run_action("secret.health", id=cred_id)
                hints.append("set" if outcome and outcome.ok and outcome.result.get("available") else "empty")
            items = [(cred_id, hint) for cred_id, hint in zip(ids, hints)] + [("+ Set a value", "for one of the ids above, or a new one declared in apx.toml")]
            choice = self.choose("Credentials", items, footer="enter inspect/set   esc back")
            if choice is None: return
            if choice == len(ids): self.screen_add_credential()
            else: self.show_result(self.run_action("secret.health", id=ids[choice]), title=ids[choice])

    def screen_add_credential(self) -> None:
        credential_id = self.read_line("Credential id (must already be declared under [credentials.<id>] in apx.toml)")
        if not credential_id: return
        value = self.read_line("Value (input is visible -- run this over a private terminal)")
        if value is None: return
        self.show_result(self.run_action("secret.set", id=credential_id, value=value), title=f"secret.set {credential_id}")

    def screen_servers(self) -> None:
        while True:
            result = self.cloud.run("host.list", actor=self.actor)
            if not result.ok: self.show_result(result); return
            hosts = result.result.get("hosts", [])
            if not hosts: self.message(["No hosts configured in apx.toml."], title="Servers"); return
            items = [(h["name"], ", ".join(h.get("tags", ())) or h.get("transport", "")) for h in hosts]
            choice = self.choose("Servers", items)
            if choice is None: return
            self.screen_host_detail(hosts[choice])

    def screen_host_detail(self, host: dict[str, Any]) -> None:
        name = host["name"]
        while True:
            items = [
                ("Status", "host.status"),
                ("Services", "list + start/stop/restart"),
                ("Info", f"tags={list(host.get('tags', ()))} groups={list(host.get('groups', ()))} roles={list(host.get('roles', ()))}"),
            ]
            choice = self.choose(f"Server: {name}", items)
            if choice is None: return
            if choice == 0: self.show_result(self.run_action("host.status", host=name))
            elif choice == 1: self.screen_services(name)
            else: self.message(_format_lines(host), title=name)

    def screen_services(self, host: str) -> None:
        while True:
            result = self.cloud.run("service.list", actor=self.actor, host=host)
            if not result.ok: self.show_result(result); return
            services = result.result.get("services", []) if isinstance(result.result, dict) else result.result
            if not services: self.message(["No services reported."], title=f"{host}: services"); return
            labels = [s["name"] if isinstance(s, dict) else str(s) for s in services]
            items = [(label, "") for label in labels]
            choice = self.choose(f"{host}: services", items)
            if choice is None: return
            self.screen_service_control(host, labels[choice])

    def screen_service_control(self, host: str, service: str) -> None:
        items = [("Status", ""), ("Start", ""), ("Stop", "destructive"), ("Restart", "destructive")]
        verbs = ["status", "start", "stop", "restart"]
        while True:
            choice = self.choose(f"{host}: {service}", items)
            if choice is None: return
            self.show_result(self.run_action(f"service.{verbs[choice]}", host=host, service=service))

    def screen_agents(self) -> None:
        while True:
            result = self.cloud.run("agent.list", actor=self.actor)
            if not result.ok: self.show_result(result); return
            agents = result.result.get("agents", [])
            if not agents: self.message(["No Standing Agents set up yet (apx agent setup)."], title="Standing Agents"); return
            items = [(a["name"], f"{a['host']} · {a['runtime']}") for a in agents]
            choice = self.choose("Standing Agents", items)
            if choice is None: return
            self.screen_agent_detail(agents[choice])

    def screen_agent_detail(self, agent: dict[str, Any]) -> None:
        name, host, unit = agent["name"], agent["host"], agent["unit_name"]
        while True:
            items = [
                ("Inspect", "current status"),
                ("Logs", "recent journal lines"),
                ("Start loop", ""),
                ("Stop loop", "destructive"),
                ("Restart loop", "destructive"),
                ("Remove", "stop tracking (add purge via CLI for full teardown)"),
            ]
            choice = self.choose(f"Agent: {name}", items)
            if choice is None: return
            if choice == 0: self.show_result(self.run_action("agent.inspect", name=name))
            elif choice == 1:
                result = self.run_action("agent.logs", name=name, lines=100)
                if result and result.ok:
                    logs = result.result.get("logs") or result.result.get("lines") or result.result
                    self.message(_format_lines(logs), title=f"{name}: logs")
                else:
                    self.show_result(result)
            elif choice == 2: self.show_result(self.run_action("service.start", host=host, service=unit))
            elif choice == 3: self.show_result(self.run_action("service.stop", host=host, service=unit))
            elif choice == 4: self.show_result(self.run_action("service.restart", host=host, service=unit))
            else:
                self.show_result(self.run_action("agent.remove", name=name, purge=False))
                return

    def screen_blueprints(self) -> None:
        while True:
            result = self.cloud.run("blueprint.list", actor=self.actor, category=None, tag=None)
            if not result.ok: self.show_result(result); return
            blueprints = result.result.get("blueprints", [])
            if not blueprints: self.message(["No Blueprints registered."], title="Blueprints"); return
            items = [(b.get("name", b.get("id", "?")), b.get("description", "")) for b in blueprints]
            choice = self.choose("Blueprints", items)
            if choice is None: return
            self.screen_blueprint_detail(blueprints[choice])

    def screen_blueprint_detail(self, blueprint: dict[str, Any]) -> None:
        blueprint_id = blueprint.get("id", blueprint.get("name"))
        while True:
            items = [("Show", "steps and inputs"), ("Apply", "destructive — runs it against a project")]
            choice = self.choose(f"Blueprint: {blueprint_id}", items)
            if choice is None: return
            if choice == 0:
                self.show_result(self.run_action("blueprint.show", blueprint=blueprint_id, version=None))
                continue
            project = self.read_line("Project name")
            if project is None: continue
            self.show_result(self.run_action("blueprint.apply", blueprint=blueprint_id, version=None, project=project, inputs={}))

    def screen_grants(self) -> None:
        result = self.cloud.run("grant.list", actor=self.actor, subject=None, include_expired=False)
        if not result.ok: self.show_result(result); return
        grants = result.result.get("grants", [])
        if not grants: self.message(["No active Grants."], title="Grants"); return
        items = [(g.get("id", "?"), f"{g.get('subject','?')} → {', '.join(g.get('actions', ()))}") for g in grants]
        choice = self.choose("Grants", items)
        if choice is not None: self.message(_format_lines(grants[choice]), title=grants[choice].get("id", "grant"))

    def screen_search(self) -> None:
        query = self.read_line("Search")
        if not query: return
        result = self.cloud.run("search.query", actor=self.actor, query=query, kinds=None, limit=25)
        self.show_result(result, title=f'search: "{query}"')

    def screen_state(self) -> None:
        while True:
            result = self.cloud.run("state.show", actor=self.actor)
            current = result.result.get("current", "?") if result.ok else "?"
            items = [("normal", "default"), ("incident", "elevated caution"), ("lockdown", "block non-essential actions")]
            choice = self.choose(f"System state (current: {current})", items)
            if choice is None: return
            name = items[choice][0]
            if name == current: continue
            reason = self.read_line("Reason", default="")
            if reason is None: continue
            self.show_result(self.run_action("state.set", name=name, reason=reason, changed_by=self.actor))

    def screen_plugins(self) -> None:
        names = sorted(self.cloud.plugin_manager.metadata)
        if not names: self.message(["No plugins loaded."], title="Plugins"); return
        items = [(name, "") for name in names]
        choice = self.choose("Plugins", items)
        if choice is not None:
            self.message(_format_lines(self.cloud.plugin_manager.inspect(names[choice])), title=names[choice])

    def screen_palette(self) -> None:
        actions = sorted(self.cloud.actions.list(), key=lambda a: a.name)
        items = [(a.name, a.description) for a in actions]
        choice = self.choose("Command palette", items, footer="type to filter by name/description   enter run/inspect   esc back")
        if choice is None: return
        action = actions[choice]
        required = list(action.schema.get("required", ()))
        if not required:
            self.show_result(self.run_action(action.name))
            return
        lines = [action.description, "", f"Requires: {', '.join(required)}", "", "Run this from a shell instead:", f"  apx run {action.name} --input '{{\"...\"}}'"]
        self.message(lines, title=action.name)


def _format_lines(value: Any, indent: int = 0) -> list[str]:
    pad = "  " * indent
    lines: list[str] = []
    if isinstance(value, dict):
        for key, item in value.items():
            if isinstance(item, (dict, list)) and item:
                lines.append(f"{pad}{key}:")
                lines.extend(_format_lines(item, indent + 1))
            else:
                lines.append(f"{pad}{key}: {item}")
    elif isinstance(value, list):
        for item in value:
            if isinstance(item, (dict, list)):
                lines.extend(_format_lines(item, indent))
                lines.append("")
            else:
                lines.append(f"{pad}- {item}")
    else:
        lines.append(f"{pad}{value}")
    return lines or [json.dumps(value)]


def run(cloud: APX, actor: str, start_screen: str | None = None) -> int:
    def _main(stdscr):
        TUI(stdscr, cloud, actor).root(start_screen)
    try:
        curses.wrapper(_main)
    except KeyboardInterrupt:
        pass
    except Quit:
        pass
    return 0
