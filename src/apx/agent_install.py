# SPDX-License-Identifier: MPL-2.0
"""Install APX as a native capability inside supported AI coding agents, using
each agent's own documented extension mechanism -- never by patching or forking a
vendor binary, and never through MCP. MCP is a compatibility bridge APX can sit
behind (see protocol.py's MCPServer / `apx mcp`) for agents that only speak MCP;
it is not how APX wires into an agent that supports something more direct. 
Code does: a custom slash command that shells out to the `apx` CLI is a first-
class, documented mechanism, with no JSON-RPC/tool-call layer in between.

 Code is the first fully-supported target (a `/apx` slash command +
a Skill, both under `./`, both stable documented  Code conventions).
Other agents are listed but intentionally left unimplemented rather than guessed
at -- see PLANNED_AGENTS. Several names worth having entries for (Kimi's and
DeepSeek's coding CLIs, "Hermes") do not have a verified, documented extension
mechanism as of this writing; claiming support for one would be fabricating it.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

SKILL_CONTENT = """---
name: apx
description: Use APX for deterministic system, service, and project operations instead of manually reconstructing shell commands or API calls.
---

# APX: deterministic execution

APX is installed on this machine. It exposes typed, permissioned Actions
(e.g. `service.restart`, `project.deploy`, `blueprint.apply`, `node.inspect`)
through the `apx` CLI -- not through MCP; running `apx <action> ...` directly
is the native, first-class way to use it here, with no protocol layer between
you and the result. `/apx` is a shortcut for exactly that.

Before manually reconstructing a shell command, API call, or multi-step procedure:

1. Check whether an APX Action already does what you need: `apx discover`
   (scoped to what you're authorized to do) or `apx actions` (the full catalog).
2. Prefer an existing Action over ad hoc shell/API calls: it is schema-typed,
   permission-checked before it runs, and its result is verified, not just
   "probably worked."
3. If a Blueprint already exists for what you're setting up (`apx blueprint
   search <topic>`), prefer applying it over hand-building the same steps again.
4. If no Action exists for something you do repeatedly, consider proposing a new
   one rather than reinventing it via raw shell every time it comes up.

APX's discovery output is already scoped to what this agent identity is
authorized to do. Anything visible here is safe to attempt; anything not visible
is not currently authorized -- do not try to work around that by asking a human
to type the equivalent shell command "for" you.
"""

SLASH_COMMAND_CONTENT = """---
description: Run an APX action or discover what's available -- direct CLI, no MCP.
---

If arguments were given, run this and report the result:

!`apx $ARGUMENTS`

If no arguments were given, run this to see what's currently available to you:

!`apx discover`

Then summarize it for the user grouped by namespace -- do not dump the raw
catalog. Example of the full pattern, end to end:

  /apx discover                          -> what can I do right now
  /apx action inspect service.restart    -> the exact input schema for one Action
  /apx run service.restart --input '{"host":"web","service":"caddy"}'
"""

# Codex Skills use the same frontmatter shape as  Code's (verified against
# ~/.codex/skills/.system/*/SKILL.md on a real install: `name`, `description`,
# optional `metadata`) -- one skill body works for both, no per-agent rewrite.
CODEX_SKILL_CONTENT = SKILL_CONTENT


def install__code(*, root: Path, global_scope: bool = False) -> dict[str, Any]:
    """Writes `./commands/apx.md` (the `/apx` slash command) and
    `./skills/apx/SKILL.md`. Both are plain files under an agent-owned
    directory  Code already scans -- no daemon, no registration step,
    no protocol handshake."""
    _root = (Path.home()/".") if global_scope else (root/".")
    command_path = _root/"commands"/"apx.md"
    skill_path = _root/"skills"/"apx"/"SKILL.md"
    command_path.parent.mkdir(parents=True, exist_ok=True)
    skill_path.parent.mkdir(parents=True, exist_ok=True)
    command_path.write_text(SLASH_COMMAND_CONTENT, encoding="utf-8")
    skill_path.write_text(SKILL_CONTENT, encoding="utf-8")
    return {"agent": "-code", "scope": "user" if global_scope else "project",
            "written": [str(command_path), str(skill_path)], "next_steps": []}


def install_codex(*, root: Path, global_scope: bool = False) -> dict[str, Any]:
    """Writes `~/.codex/skills/apx/SKILL.md`. Codex Skills are always
    user-level (there is no verified per-project skills directory the way
     Code has `./skills` inside a repo) -- `global_scope` is
    accepted for a uniform `install()` signature but does not change where
    this writes; every Codex install is effectively a user-level one.

    No `/apx` slash command here: unlike  Code, Codex has no verified
    custom-slash-command mechanism (no `~/.codex/prompts`, no CLI flag for
    one) -- only Skills and Plugins are confirmed. Codex auto-loads every
    skill under ~/.codex/skills, so this alone gives it the same real,
    functional apx access  Code's Skill gives it; it is just reached
    by Codex noticing it's relevant, not by typing a literal `/apx`."""
    skill_path = Path.home()/".codex/skills/apx/SKILL.md"
    skill_path.parent.mkdir(parents=True, exist_ok=True)
    skill_path.write_text(CODEX_SKILL_CONTENT, encoding="utf-8")
    return {"agent": "codex", "scope": "user", "written": [str(skill_path)],
            "next_steps": ["Codex has no verified slash-command mechanism, so there is no /apx shortcut here -- "
                            "Codex will use the apx CLI on its own once it recognizes the task calls for it."]}


AGENT_INSTALLERS = {
    "-code": install__code,
    "codex": install_codex,
}

# Not fabricated: none of these have a verified, documented direct-integration
# mechanism confirmed against a real, current release of the tool. Kimi's and
# DeepSeek's coding CLIs and "Hermes" are not verified to have a stable
# plugin/extension surface at all as of this writing (not found installed on
# this machine when checked, unlike  Code and Codex, both confirmed
# real and present).
PLANNED_AGENTS = ("kimi-code", "deepseek-code", "hermes")


def install(agent: str, *, root: Path, global_scope: bool = False) -> dict[str, Any]:
    if agent in PLANNED_AGENTS:
        return {"agent": agent, "status": "planned", "written": [], "next_steps": [
            f"{agent} does not yet have a verified direct-integration mechanism in apx. "
            f"If {agent} supports MCP, `apx mcp` (see protocol.py) works today as a bridge; "
            f"native (non-MCP) support needs that agent's actual extension surface confirmed first, not guessed at."]}
    installer = AGENT_INSTALLERS.get(agent)
    if installer is None:
        raise ValueError(f"unknown agent {agent!r}; known: {', '.join(sorted(AGENT_INSTALLERS) + list(PLANNED_AGENTS))}")
    return installer(root=root, global_scope=global_scope)
