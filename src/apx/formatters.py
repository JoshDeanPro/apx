# SPDX-License-Identifier: MPL-2.0
"""Human-friendly CLI formatters for APX using Rich."""
from __future__ import annotations

import json
from typing import Any

from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.text import Text
from rich import box

console = Console()


def print_json(data: Any) -> None:
    """Print clean JSON for machine-readable output."""
    if hasattr(data, "to_dict"):
        data = data.to_dict()
    print(json.dumps(data, indent=2, ensure_ascii=False))


def format_risk_badge(risk: str | None) -> Text:
    t = Text()
    r = str(risk or "read").lower()
    if r == "read":
        t.append(" READ ", style="bold green on black")
    elif r in {"account_change", "mutation"}:
        t.append(" MUTATE ", style="bold yellow on black")
    elif r in {"destructive", "shutdown"}:
        t.append(" DESTRUCT ", style="bold white on red")
    else:
        t.append(f" {r.upper()} ", style="bold cyan on black")
    return t


def format_confirm_badge(confirm: str | None) -> Text:
    t = Text()
    c = str(confirm or "none").lower()
    if c == "none":
        t.append(" none ", style="dim")
    elif c == "confirm":
        t.append(" confirm ", style="bold yellow")
    elif c == "elevated":
        t.append(" elevated ", style="bold red")
    else:
        t.append(f" {c} ", style="cyan")
    return t


def render_actions_table(actions: list[Any]) -> None:
    if not actions:
        console.print(Panel(Text("No actions found.", style="dim"), title="APX Actions Catalog", border_style="cyan"))
        return

    table = Table(
        title=f"APX Actions Catalog ({len(actions)} actions)",
        title_style="bold cyan",
        box=box.ROUNDED,
        header_style="bold white on dark_blue",
        show_lines=False,
    )
    table.add_column("Action ID", style="bold cyan", no_wrap=True)
    table.add_column("Risk", justify="center")
    table.add_column("Confirm", justify="center")
    table.add_column("Description", style="white")

    for action in actions:
        name = getattr(action, "name", None) or getattr(action, "id", None) or str(action.get("id", ""))
        desc = getattr(action, "description", "") or (action.get("description", "") if isinstance(action, dict) else "")
        risk = getattr(action, "risk", "read") if hasattr(action, "risk") else (action.get("risk", "read") if isinstance(action, dict) else "read")
        confirm = getattr(action, "confirmation", "none") if hasattr(action, "confirmation") else (action.get("confirmation", "none") if isinstance(action, dict) else "none")

        table.add_row(name, format_risk_badge(risk), format_confirm_badge(confirm), desc)

    console.print(table)


def render_action_detail(action: Any) -> None:
    data = action.to_dict() if hasattr(action, "to_dict") else action
    action_id = data.get("id", data.get("name", "Unknown Action"))
    desc = data.get("description", "")
    risk = data.get("risk", "read")
    confirm = data.get("confirmation", "none")
    read_only = data.get("read_only", False)
    destructive = data.get("destructive", False)
    idempotent = data.get("idempotent", False)
    provenance = data.get("provenance", "native_provider")
    input_schema = data.get("input_schema", {})
    props = input_schema.get("properties", {})
    reqs = input_schema.get("required", [])

    body = Text()
    body.append(f"{desc}\n\n", style="white")
    body.append("Properties:\n", style="bold cyan")
    body.append(f"  • Risk Level:     ", style="dim")
    body.append_text(format_risk_badge(risk))
    body.append(f"\n  • Confirmation:   ", style="dim")
    body.append_text(format_confirm_badge(confirm))
    body.append(f"\n  • Read Only:      {'Yes' if read_only else 'No'}\n", style="dim")
    body.append(f"  • Destructive:    {'Yes' if destructive else 'No'}\n", style="dim")
    body.append(f"  • Idempotent:     {'Yes' if idempotent else 'No'}\n", style="dim")
    body.append(f"  • Provenance:     {provenance}\n", style="dim")

    if props:
        body.append("\nInput Parameters:\n", style="bold cyan")
        for param, spec in props.items():
            req_mark = " (required)" if param in reqs else ""
            p_type = spec.get("type", "any")
            p_desc = spec.get("description", "")
            desc_text = f" — {p_desc}" if p_desc else ""
            body.append(f"  • {param}", style="bold yellow")
            body.append(f": {p_type}{req_mark}", style="green")
            body.append(f"{desc_text}\n", style="dim")
    else:
        body.append("\nInput Parameters: None (zero-argument action)\n", style="dim")

    panel = Panel(body, title=f"⚡ Action: {action_id}", border_style="cyan", box=box.ROUNDED)
    console.print(panel)


def render_resources_table(resources: list[Any]) -> None:
    if not resources:
        console.print(Panel(Text("No resources discovered.", style="dim"), title="APX Resources", border_style="cyan"))
        return

    table = Table(
        title=f"APX Resources ({len(resources)} total)",
        title_style="bold cyan",
        box=box.ROUNDED,
        header_style="bold white on dark_blue",
    )
    table.add_column("Resource ID", style="bold cyan", no_wrap=True)
    table.add_column("Kind", style="bold yellow")
    table.add_column("Name", style="white")
    table.add_column("Tags", style="dim")

    for res in resources:
        if isinstance(res, dict):
            rid = res.get("id", "")
            kind = res.get("kind", "")
            name = res.get("name", "")
            tags = res.get("tags", [])
        else:
            rid = getattr(res, "id", "")
            kind = getattr(res, "kind", "")
            name = getattr(res, "name", "")
            tags = getattr(res, "tags", [])
        tags_str = ", ".join(tags) if tags else "—"
        table.add_row(str(rid), f"[{kind}]", str(name), tags_str)

    console.print(table)


def render_providers_table(providers: list[Any]) -> None:
    if not providers:
        console.print(Panel(Text("No connected action providers.", style="dim"), title="APX Providers", border_style="cyan"))
        return

    table = Table(
        title=f"Connected Action Providers ({len(providers)})",
        title_style="bold cyan",
        box=box.ROUNDED,
        header_style="bold white on dark_blue",
    )
    table.add_column("Provider ID", style="bold cyan", no_wrap=True)
    table.add_column("Name", style="white")
    table.add_column("Actions", justify="right", style="green")
    table.add_column("Status", justify="center")

    for p in providers:
        if isinstance(p, dict):
            pid = p.get("id", "")
            name = p.get("name", "")
            actions_count = p.get("actions", 0)
        elif hasattr(p, "provider"):
            pid = getattr(p.provider, "id", "")
            name = getattr(p.provider, "name", "")
            actions_count = len(getattr(p, "actions", []))
        else:
            pid = getattr(p, "id", "")
            name = getattr(p, "name", "")
            actions_count = len(getattr(p, "actions", [])) if hasattr(p, "actions") else 0
        status = Text(" ONLINE ", style="bold green on black")
        table.add_row(str(pid), str(name), str(actions_count), status)

    console.print(table)


def render_whoami(data: dict[str, Any]) -> None:
    actor_id = data.get("actor", data.get("id", "human:operator"))
    kind = data.get("kind", "human")
    roles = data.get("roles", ["admin"])
    open_world = data.get("open_world", True)

    text = Text()
    text.append(f"Actor Identity: ", style="dim")
    text.append(f"{actor_id}\n", style="bold cyan")
    text.append(f"Principal Kind: ", style="dim")
    text.append(f"{kind}\n", style="bold yellow")
    text.append(f"Assigned Roles: ", style="dim")
    text.append(f"{', '.join(roles) if roles else 'none'}\n", style="bold green")
    text.append(f"Policy Mode:    ", style="dim")
    text.append(f"{'Unrestricted (no role boundaries defined)' if open_world else 'Role-Based Policy Enforced'}\n", style="dim")

    panel = Panel(text, title="👤 APX Actor & Identity", border_style="cyan", box=box.ROUNDED)
    console.print(panel)


def render_policy_explain(data: dict[str, Any]) -> None:
    decision = data.get("decision", "denied")
    actor = data.get("actor", "")
    action = data.get("action", "")
    reason = data.get("reason", "")
    matched_rule = data.get("matched_rule")

    text = Text()
    text.append("Evaluation: ", style="dim")
    if decision == "allowed":
        text.append(" ALLOWED \n", style="bold black on green")
    else:
        text.append(" DENIED \n", style="bold white on red")

    text.append(f"Actor:      {actor}\n", style="cyan")
    text.append(f"Action:     {action}\n", style="yellow")
    text.append(f"Reason:     {reason}\n", style="white")
    if matched_rule:
        text.append(f"Rule:       {json.dumps(matched_rule)}\n", style="dim")

    panel = Panel(text, title="🛡️ APX Policy Decision", border_style="green" if decision == "allowed" else "red", box=box.ROUNDED)
    console.print(panel)


def render_action_result(result: Any) -> None:
    data = result.to_dict() if hasattr(result, "to_dict") else result
    ok = data.get("ok", False)
    status = data.get("status", "completed" if ok else "failed")
    action_name = data.get("action", "")
    res_data = data.get("result", {})
    error = data.get("error")
    receipt = data.get("receipt")

    header_text = Text()
    if ok:
        header_text.append(" ✓ SUCCESS ", style="bold black on green")
    else:
        header_text.append(" ✗ FAILED ", style="bold white on red")
    header_text.append(f"  Action: [bold cyan]{action_name}[/bold cyan]  Status: [bold]{status}[/bold]\n\n")

    if receipt:
        rid = receipt.get("receipt_id", "")
        ts = receipt.get("timestamp", "")
        header_text.append(f"Receipt ID: {rid}\nTimestamp:  {ts}\n\n", style="dim")

    if ok:
        if res_data is not None:
            if isinstance(res_data, dict):
                header_text.append(json.dumps(res_data, indent=2), style="white")
            elif isinstance(res_data, list):
                header_text.append(json.dumps(res_data, indent=2), style="white")
            else:
                header_text.append(str(res_data), style="white")
        else:
            header_text.append("Action completed with no return data.", style="dim")
    else:
        err_msg = error.get("message", str(error)) if isinstance(error, dict) else str(error)
        err_code = error.get("code", "") if isinstance(error, dict) else ""
        header_text.append(f"Error [{err_code}]: {err_msg}\n", style="bold red")

    panel = Panel(header_text, title=f"⚡ Execution Output", border_style="green" if ok else "red", box=box.ROUNDED)
    console.print(panel)


def render_conformance(data: dict[str, Any]) -> None:
    ok = data.get("ok", False)
    phases = data.get("phases", [])
    checked = data.get("actions_checked", 0)

    text = Text()
    if ok:
        text.append(" CONFORMANCE PASS \n\n", style="bold black on green")
    else:
        text.append(" CONFORMANCE FAIL \n\n", style="bold white on red")

    text.append(f"Protocol Version:  0.1\n", style="cyan")
    text.append(f"Phases Validated:  {', '.join(phases)}\n", style="white")
    text.append(f"Actions Checked:   {checked}\n", style="green")

    panel = Panel(text, title="📋 APX Protocol Conformance Suite", border_style="green" if ok else "red", box=box.ROUNDED)
    console.print(panel)
