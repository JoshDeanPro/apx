# SPDX-License-Identifier: MPL-2.0
"""Standing Agents: the same pattern as `palis-autopilot.service` on the production
VPS, generalized so `apx agent setup` can stand up a new one on any configured Node
in one call instead of hand-writing a systemd unit, a loop script, and a prompt.

What that service actually does, and what this module reproduces: a `claude`
iteration runs to completion, one at a time, forever, under systemd. Around the
invocation itself: a single writer (flock) so nothing else can edit the repository
mid-iteration, real usage-limit-reset parsing (Claude Code reports a rate-limited
iteration with an epoch reset time; this backs off until then instead of hammering
a closed door), exponential backoff on ordinary failures, and log rotation so the
iteration log directory never grows unbounded. None of that is invented here --
it is the actual, running production recipe, with only the project-specific paths
and prompt content made into parameters.

A Standing Agent is a systemd (or launchd) service like any other -- once set up,
`service.start/stop/restart/status` (actions.py) already control it. This module
only owns the "make one exist" and "which of these have I created" parts.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .discovery import inspect_host
from .files import atomic_write
from .models import Host
from .transports import transport_for

RUN_SH_TEMPLATE = r'''#!/usr/bin/env bash
# Managed by apx (agent.setup) -- generated, not hand-edited. Re-run
# `apx agent setup __NAME__ ...` to change parameters; edits here are lost.
set -uo pipefail

export HOME=__HOME__
export PATH=__AGENT_PATH__

REPO=__REPO__
STATE_DIR=__STATE_DIR__
PROMPT_FILE=__PROMPT_FILE__
TODO_FILE="${STATE_DIR}/TODO.md"
STATE_FILE="${STATE_DIR}/state.md"
LOG_DIR="${STATE_DIR}/iterations"
LOCK_FILE=__LOCK_FILE__

_MODEL_DEFAULT=__MODEL__
_EFFORT_DEFAULT=__EFFORT__
_TIMEOUT_DEFAULT=__TIMEOUT__
_IDLE_GAP_DEFAULT=__IDLE_GAP__
_ERROR_GAP_DEFAULT=__ERROR_GAP__
MODEL="${APX_AGENT_MODEL:-$_MODEL_DEFAULT}"
EFFORT="${APX_AGENT_EFFORT:-$_EFFORT_DEFAULT}"
ITERATION_TIMEOUT="${APX_AGENT_TIMEOUT:-$_TIMEOUT_DEFAULT}"
IDLE_GAP="${APX_AGENT_IDLE_GAP:-$_IDLE_GAP_DEFAULT}"
ERROR_GAP="${APX_AGENT_ERROR_GAP:-$_ERROR_GAP_DEFAULT}"
MAX_ITERATION_LOGS=__MAX_LOGS__

mkdir -p "$STATE_DIR" "$LOG_DIR"

log() { printf '%s %s\n' "$(date -Is)" "$*"; }

# --- portable helpers: macOS ships neither GNU `timeout`/`flock` nor GNU
# `date -d`. These make the loop work identically under systemd (GNU
# userland) and launchd (BSD userland) without requiring coreutils/util-linux
# to be installed on a Mac Node. ---------------------------------------------
iso_from_epoch() {
  date -d "@$1" -Is 2>/dev/null || date -r "$1" '+%Y-%m-%dT%H:%M:%S%z' 2>/dev/null || echo "epoch:$1"
}

# Runs "$@" in the background, kills it (TERM then KILL) if it outlives $1
# seconds, and returns 124 on timeout -- same convention as GNU `timeout`.
run_with_timeout() {
  local secs="$1"; shift
  local sentinel; sentinel="$(mktemp -u)"
  "$@" &
  local child=$!
  ( sleep "$secs"; touch "$sentinel" 2>/dev/null; kill -TERM "$child" 2>/dev/null; sleep 120; kill -KILL "$child" 2>/dev/null ) &
  local watchdog=$!
  wait "$child" 2>/dev/null; local code=$?
  kill "$watchdog" 2>/dev/null; wait "$watchdog" 2>/dev/null
  if [[ -e "$sentinel" ]]; then rm -f "$sentinel"; return 124; fi
  return "$code"
}

__BIN_RESOLVE__
[[ -d "$REPO" ]]        || { log "FATAL: no repository at $REPO"; exit 1; }
[[ -f "$PROMPT_FILE" ]] || { log "FATAL: no prompt at $PROMPT_FILE"; exit 1; }

if [[ ! -f "$TODO_FILE" ]]; then
  cat > "$TODO_FILE" <<'EOF'
# __NAME__ TODO

This agent reads this at the start of every iteration and maintains it.
Humans can edit it freely; put the most important thing first.

## Now

_(nothing queued)_

## Later

## Done

EOF
  log "created $TODO_FILE"
fi

__RATE_LIMIT_FUNCS__

note_state() { printf '\n<!-- agent %s: %s -->\n' "$(date -Is)" "$*" >> "$STATE_FILE" 2>/dev/null || true; }

# --- only one writer ---------------------------------------------------------
# mkdir is atomic on every POSIX filesystem this needs to run on, and needs no
# `flock` binary (absent from stock macOS) -- portable in exchange for one
# real limitation flock does not have: a lock left by a killed-with-SIGKILL
# process is not auto-released. The trap below releases it on any normal exit
# (including TERM), which is the only path a killed-with-SIGKILL process skips.
LOCK_DIR="${LOCK_FILE}.d"
if ! mkdir "$LOCK_DIR" 2>/dev/null; then
  log "another agent holds $LOCK_DIR; this instance is standing down"
  exit 0
fi
trap 'rmdir "$LOCK_DIR" 2>/dev/null' EXIT

cd "$REPO" || exit 1
log "agent __NAME__ starting: model=$MODEL effort=$EFFORT repo=$REPO"
trap 'log "received termination signal; finishing"; exit 0' TERM INT

iteration=0
consecutive_failures=0

while true; do
  iteration=$((iteration + 1))
  stamp="$(date -u +%Y%m%dT%H%M%SZ)"
  iter_log="${LOG_DIR}/${stamp}.jsonl"

  log "=== iteration ${iteration} starting (log: ${iter_log}) ==="

__INVOKE__
  exit_code=$?

  log "iteration ${iteration} exited ${exit_code}"

  if looks_rate_limited "$iter_log"; then
    now="$(date +%s)"
    if reset_epoch="$(rate_limit_reset_epoch "$iter_log")"; then
      wait_for=$(( reset_epoch - now + 60 ))
      (( wait_for < 60 )) && wait_for=60
      log "usage limit reached; resets $(iso_from_epoch "${reset_epoch}"), sleeping ${wait_for}s"
      note_state "usage limit; sleeping until $(iso_from_epoch "$(( reset_epoch + 60 ))")"
    else
      wait_for=3600
      log "usage limit reached with no parsable reset time; sleeping ${wait_for}s"
      note_state "usage limit with no reset timestamp; slept 1h"
    fi
    sleep "$wait_for"
    continue
  fi

  if (( exit_code == 124 )); then
    log "iteration hit the ${ITERATION_TIMEOUT}s ceiling and was stopped"
    note_state "iteration ${iteration} timed out after ${ITERATION_TIMEOUT}s"
    consecutive_failures=$((consecutive_failures + 1))
  elif (( exit_code != 0 )); then
    log "iteration failed (exit ${exit_code}); tail follows"
    tail -n 15 "$iter_log" | sed 's/^/    /'
    consecutive_failures=$((consecutive_failures + 1))
  else
    consecutive_failures=0
  fi

  ls -1t "${LOG_DIR}"/*.jsonl 2>/dev/null | tail -n +$((MAX_ITERATION_LOGS + 1)) | xargs -r rm -f

  if (( consecutive_failures > 0 )); then
    shift_by=$(( consecutive_failures > 3 ? 3 : consecutive_failures - 1 ))
    backoff=$(( ERROR_GAP * (1 << shift_by) ))
    (( backoff > 3600 )) && backoff=3600
    log "${consecutive_failures} consecutive failure(s); next attempt in ${backoff}s"
    sleep "$backoff"
  else
    log "next iteration in ${IDLE_GAP}s"
    sleep "$IDLE_GAP"
  fi
done
'''

UNIT_TEMPLATE = r'''[Unit]
Description=__DESCRIPTION__
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=__USER__
WorkingDirectory=__REPO__

Environment=HOME=__HOME__
Environment=PATH=__AGENT_PATH__
Environment=APX_AGENT_MODEL=__MODEL__
Environment=APX_AGENT_EFFORT=__EFFORT__
Environment=APX_AGENT_TIMEOUT=__TIMEOUT__
Environment=APX_AGENT_IDLE_GAP=__IDLE_GAP__

ExecStart=__RUN_SCRIPT__

Restart=always
RestartSec=60

KillSignal=SIGTERM
TimeoutStopSec=300

StandardOutput=journal
StandardError=journal
SyslogIdentifier=__NAME__

# Deliberately not sandboxed the way ordinary services are: this agent edits a
# repository, may restart units, and may deploy. Set true by hand only once
# you have verified the sandbox does not block the work this agent needs to do.
NoNewPrivileges=false

[Install]
WantedBy=multi-user.target
'''

# launchd equivalent of UNIT_TEMPLATE, for Mac Nodes -- same run.sh, different
# supervisor. RunAtLoad is deliberately false: writing this file must not start
# the agent, matching the systemd path (bootstrap loads it; kickstart starts it,
# see deploy()). KeepAlive true is launchd's closest match to Restart=always.
LAUNCHD_PLIST_TEMPLATE = r'''<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>__UNIT_NAME__</string>
    <key>ProgramArguments</key>
    <array>
        <string>__RUN_SCRIPT__</string>
    </array>
    <key>WorkingDirectory</key>
    <string>__REPO__</string>
    <key>EnvironmentVariables</key>
    <dict>
        <key>PATH</key>
        <string>__AGENT_PATH__</string>
        <key>APX_AGENT_MODEL</key>
        <string>__MODEL__</string>
        <key>APX_AGENT_EFFORT</key>
        <string>__EFFORT__</string>
        <key>APX_AGENT_TIMEOUT</key>
        <string>__TIMEOUT__</string>
        <key>APX_AGENT_IDLE_GAP</key>
        <string>__IDLE_GAP__</string>
    </dict>
    <key>RunAtLoad</key>
    <false/>
    <key>KeepAlive</key>
    <true/>
    <key>StandardOutPath</key>
    <string>__STATE_DIR__/agent.log</string>
    <key>StandardErrorPath</key>
    <string>__STATE_DIR__/agent.log</string>
</dict>
</plist>
'''

PROMPT_TEMPLATE = r'''# __NAME__

You are the standing engineer for __PROJECT_DESCRIPTION__. You run unattended,
on a loop. Nobody is watching this iteration. Everything you do persists,
including your mistakes.

Repository: `__REPO__`
Your state: `__STATE_DIR__`

## Read these first, every time

1. `__STATE_DIR__/TODO.md` -- the work queue. You own it.
2. `__STATE_DIR__/state.md` -- what previous iterations learned.
3. __STATUS_COMMAND__

Do not re-derive what state.md already records. Do correct it when it is wrong.

## Pick one thing

Take the highest-value item from TODO.md and finish it. One coherent piece of
work per iteration, taken to the point where it is committed, deployed (if
applicable) and verified -- not five started and none landed.

### Work that is worth doing

- A bug a user would actually hit.
- A feature in TODO.md that a human asked for.
- A test that would have caught something that broke.
- Finishing something a previous iteration left half-done.
- Correcting something a previous iteration got wrong.

### Work that is not

Do not invent work to look busy. Specifically, do not reformat/rename/"tidy"
working code nobody complained about, add tests that only restate the
implementation, refactor for its own sake, or re-solve something already
solved in an earlier iteration.

**If there is nothing genuinely worth doing, do nothing.** Append a line to
state.md saying you looked and found nothing, and exit. An honest idle
iteration is a success; invented work is a failure.

## How to finish a piece of work

Written, committed, built, deployed, running and verified are different
things. Get to verified.

__TEST_COMMAND__

## Fill this in for your project

Replace this section with the commands/conventions specific to __PROJECT_DESCRIPTION__:
build, deploy, restart, and how to check the result actually took effect.
'''


# Configurable per coding-agent runtime: which binary to resolve, how to invoke it
# for one non-interactive iteration, and how to detect a rate-limited iteration.
# "claude" is the exact recipe from the real palis-autopilot.service invocation
# (verified=True: this is running in production, not guessed at). "codex" is a
# best-effort scaffold, not yet run in anger -- see its `invoke` comment. Adding
# a new runtime means adding one more entry here; nothing else in this module
# needs to change.
AGENT_RUNTIMES: dict[str, dict[str, Any]] = {
    "claude": {
        "verified": True,
        "bin_resolve": r'''CLAUDE_BIN="$(command -v claude 2>/dev/null || true)"
if [[ -z "$CLAUDE_BIN" || ! -x "$CLAUDE_BIN" ]]; then
  log "FATAL: claude executable not found on PATH"; exit 127
fi''',
        "invoke": r'''  run_with_timeout "$ITERATION_TIMEOUT" \
    "$CLAUDE_BIN" \
      --print \
      --model "$MODEL" \
      --effort "$EFFORT" \
      --permission-mode auto \
      --output-format stream-json \
      --verbose \
      "$(cat "$PROMPT_FILE")" \
    > "$iter_log" 2>&1''',
        "rate_limit_funcs": r'''# --- usage limits: parse the real reset time, do not guess -----------------
rate_limit_reset_epoch() {
  local file="$1" now epoch
  now="$(date +%s)"
  if command -v jq >/dev/null 2>&1; then
    epoch="$(
      jq -Rr '
        fromjson? | select(.type == "rate_limit_event" and .rate_limit_info.status == "rejected")
        | .rate_limit_info.resetsAt // empty
      ' "$file" 2>/dev/null | grep -E '^[0-9]{10}$' | sort -n | head -1
    )"
    if [[ -n "$epoch" ]] && (( epoch > now )); then echo "$epoch"; return 0; fi
  fi
  epoch="$(grep -oiE 'usage limit reached\|[0-9]{10}' "$file" 2>/dev/null | grep -oE '[0-9]{10}' | sort -n | head -1)"
  if [[ -n "$epoch" ]] && (( epoch > now )); then echo "$epoch"; return 0; fi
  return 1
}

looks_rate_limited() {
  local file="$1"
  if command -v jq >/dev/null 2>&1; then
    if jq -Rr '
      fromjson? | select(.type == "rate_limit_event" and .rate_limit_info.status == "rejected") | "rejected"
    ' "$file" 2>/dev/null | grep -qx 'rejected'; then return 0; fi
  fi
  grep -qiE "usage limit reached|you.?ve hit your (session|weekly|opus) limit" "$file" 2>/dev/null
}''',
    },
    "codex": {
        "verified": False,
        "bin_resolve": r'''CODEX_BIN="$(command -v codex 2>/dev/null || true)"
if [[ -z "$CODEX_BIN" || ! -x "$CODEX_BIN" ]]; then
  log "FATAL: codex executable not found on PATH"; exit 127
fi''',
        "invoke": r'''  # Best-effort invocation -- verify these flags against `codex --help` on the
  # installed version before relying on this in production. Unlike the claude
  # runtime above, this has not been confirmed against a real, running agent.
  run_with_timeout "$ITERATION_TIMEOUT" \
    "$CODEX_BIN" exec \
      --full-auto \
      --model "$MODEL" \
      "$(cat "$PROMPT_FILE")" \
    > "$iter_log" 2>&1''',
        "rate_limit_funcs": r'''# Codex's rate-limit-event wire shape is not verified the way Claude Code's
# is (see AGENT_RUNTIMES in apx's agents.py) -- rather than guess at a JSON
# shape and risk silently mis-detecting, this always reports "not rate
# limited" and lets the ordinary failure backoff below (exponential, capped
# at 1h) handle a rate-limited iteration as a normal failure. Less precise,
# never wrong.
looks_rate_limited() { return 1; }
rate_limit_reset_epoch() { return 1; }''',
    },
}


def _substitute(template: str, values: dict[str, str]) -> str:
    text = template
    for key, value in values.items(): text = text.replace(f"__{key}__", value)
    return text


def _shell_literal(value: str) -> str:
    """Wraps `value` as a single-quoted bash literal, safe to splice into an
    unquoted `KEY=__KEY__` assignment regardless of content -- bash's own
    quote-removal at assignment time restores the exact string, and embedded
    single quotes are escaped by closing/re-opening the quoted run (the
    standard '\\'' trick), so nothing between the quotes is ever re-parsed as
    shell syntax."""
    return "'" + str(value).replace("'", "'\\''") + "'"


# Keys substituted into RUN_SH_TEMPLATE that land in an unquoted `KEY=__KEY__`
# (or, for the *_DEFAULT variables, single-quoted-by-construction) assignment
# and therefore must be shell-literal-escaped -- see _shell_literal.
_RUN_SH_LITERAL_KEYS = frozenset({
    "HOME", "AGENT_PATH", "REPO", "STATE_DIR", "PROMPT_FILE", "LOCK_FILE",
    "MODEL", "EFFORT", "TIMEOUT", "IDLE_GAP", "ERROR_GAP", "MAX_LOGS",
})


class AgentError(RuntimeError): pass


def _now() -> str: return datetime.now(timezone.utc).isoformat()


def _default_paths(name: str, user: str, init_system: str) -> dict[str, str]:
    if init_system == "launchd":
        # Everything under $HOME: a LaunchAgent runs as the user, needs no sudo,
        # and macOS does not have systemd's /etc/systemd, /run, /var/lib, /opt
        # conventions to lean on. No spaces in any of these -- they are spliced
        # into run.sh as unquoted bash literals (STATE_DIR=__STATE_DIR__).
        home = "/var/root" if user == "root" else f"/Users/{user}"
        base = f"{home}/.apx-agents/{name}"
        label = f"com.apx.agent.{name}"
        return {
            "HOME": home, "STATE_DIR": base,
            "PROMPT_FILE": f"{base}/PROMPT.md", "RUN_SCRIPT": f"{base}/run.sh",
            "LOCK_FILE": f"{base}/agent.lock",
            "UNIT_PATH": f"{home}/Library/LaunchAgents/{label}.plist", "UNIT_NAME": label,
        }
    home = "/root" if user == "root" else f"/home/{user}"
    state_dir = f"/var/lib/apx-agents/{name}"
    return {
        "HOME": home,
        "STATE_DIR": state_dir,
        "PROMPT_FILE": f"/opt/apx-agents/{name}/PROMPT.md",
        "RUN_SCRIPT": f"/opt/apx-agents/{name}/run.sh",
        "LOCK_FILE": f"/run/apx-agent-{name}.lock",
        "UNIT_PATH": f"/etc/systemd/system/apx-agent-{name}.service",
        "UNIT_NAME": f"apx-agent-{name}.service",
    }


def render(name: str, *, repo: str, description: str = "", project_description: str = "", user: str = "root",
           init_system: str = "systemd", runtime: str = "claude", model: str = "opus", effort: str = "medium",
           timeout: int = 7200, idle_gap: int = 1800, error_gap: int = 600, max_logs: int = 200,
           status_command: str = "(no status command configured)",
           test_command: str = "(no test command configured -- fill this in before enabling)",
           agent_path: str = "/root/.local/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin") -> dict[str, str]:
    """Renders run.sh, the supervisor unit (systemd .service or launchd .plist),
    and a PROMPT.md skeleton. Pure -- no I/O, so this is trivially testable and
    callable from a dry-run/plan path."""
    if not name or not name.replace("-", "").replace("_", "").isalnum():
        raise AgentError(f"invalid agent name {name!r}; use letters, digits, - and _ only")
    if runtime not in AGENT_RUNTIMES:
        raise AgentError(f"unknown agent runtime {runtime!r}; known: {', '.join(sorted(AGENT_RUNTIMES))}")
    if init_system not in ("systemd", "launchd"):
        raise AgentError(f"unknown init system {init_system!r}; known: systemd, launchd")
    # Every one of these is spliced into a generated run.sh (executed as root/the
    # service user under systemd or launchd) and/or a systemd .service / launchd
    # .plist file. A newline would let a value inject an extra unit-file directive
    # (e.g. a rogue ExecStart=); shell-literal-escaping (below) handles the bash
    # side, but there is no equivalent safe-splice for a multi-line value in an
    # ini-style unit file, so it is rejected outright rather than half-escaped.
    for field_name, field_value in (("repo", repo), ("description", description), ("project_description", project_description),
                                     ("user", user), ("status_command", status_command), ("test_command", test_command), ("agent_path", agent_path)):
        if any(char in field_value for char in ("\n", "\r", "\x00")):
            raise AgentError(f"{field_name} must not contain newlines or NUL bytes")
    paths = _default_paths(name, user, init_system)
    runtime_config = AGENT_RUNTIMES[runtime]
    run_sh = _substitute(RUN_SH_TEMPLATE, {
        "BIN_RESOLVE": runtime_config["bin_resolve"],
        "RATE_LIMIT_FUNCS": runtime_config["rate_limit_funcs"],
        "INVOKE": runtime_config["invoke"],
    })
    values = {
        "NAME": name, "REPO": repo, "USER": user, "MODEL": model, "EFFORT": effort,
        "TIMEOUT": str(timeout), "IDLE_GAP": str(idle_gap), "ERROR_GAP": str(error_gap),
        "MAX_LOGS": str(max_logs), "AGENT_PATH": agent_path,
        "DESCRIPTION": description or f"apx Standing Agent: {name}",
        "PROJECT_DESCRIPTION": project_description or name,
        "STATUS_COMMAND": status_command, "TEST_COMMAND": test_command,
        **paths,
    }
    unit_template = LAUNCHD_PLIST_TEMPLATE if init_system == "launchd" else UNIT_TEMPLATE
    # run.sh is bash, not the ini/XML/markdown the other three templates are -- values
    # landing in it get shell-literal-escaped so nothing in them (repo path, agent_path,
    # etc.) can be interpreted as shell syntax, regardless of content.
    shell_safe_values = {key: (_shell_literal(value) if key in _RUN_SH_LITERAL_KEYS else value) for key, value in values.items()}
    return {
        "runtime": runtime, "runtime_verified": runtime_config["verified"], "init_system": init_system,
        "run_sh": _substitute(run_sh, shell_safe_values),
        "unit": _substitute(unit_template, values),
        "prompt": _substitute(PROMPT_TEMPLATE, values),
        "run_script_path": paths["RUN_SCRIPT"],
        "prompt_path": paths["PROMPT_FILE"],
        "unit_path": paths["UNIT_PATH"],
        "unit_name": paths["UNIT_NAME"],
        "state_dir": paths["STATE_DIR"],
    }


def _write_remote_file(host: Host, path: str, content: str, *, mode: str | None = None) -> None:
    transport = transport_for(host)
    directory = path.rsplit("/", 1)[0]
    result = transport.run(["mkdir", "-p", directory], timeout=15)
    if not result.ok: raise AgentError(f"could not create {directory} on {host.name}: {result.stderr.strip()}")
    result = transport.run(["tee", path], timeout=15, input_text=content)
    if not result.ok: raise AgentError(f"could not write {path} on {host.name}: {result.stderr.strip()}")
    if mode:
        result = transport.run(["chmod", mode, path], timeout=15)
        if not result.ok: raise AgentError(f"could not chmod {path} on {host.name}: {result.stderr.strip()}")


def detect_init_system(host: Host) -> str:
    capabilities = inspect_host(host)["capabilities"]
    if capabilities["systemd"]["available"]: return "systemd"
    if capabilities["launchd"]["available"]: return "launchd"
    raise AgentError(f"{host.name} has neither systemd nor launchd; agent.setup has no supervisor to use")


def deploy(host: Host, rendered: dict[str, Any], *, force: bool = False) -> dict[str, Any]:
    """Writes run.sh/unit/prompt to the host and loads the supervisor config.
    Never starts or enables the agent itself -- that is a separate, explicit step
    (service.start / `apx agent setup --start`), since this brings a real
    autonomous, permission-mode=auto loop into existence and starting one is
    consequential in a way writing its config to disk is not."""
    init_system = rendered["init_system"]
    transport = transport_for(host)
    prompt_exists = transport.run(["test", "-f", rendered["prompt_path"]], timeout=10).ok
    wrote_prompt = force or not prompt_exists
    if wrote_prompt: _write_remote_file(host, rendered["prompt_path"], rendered["prompt"])
    _write_remote_file(host, rendered["run_script_path"], rendered["run_sh"], mode="755")
    _write_remote_file(host, rendered["unit_path"], rendered["unit"])
    if init_system == "systemd":
        reload_result = transport.run(["systemctl", "daemon-reload"], timeout=15)
        if not reload_result.ok: raise AgentError(f"systemctl daemon-reload failed on {host.name}: {reload_result.stderr.strip()}")
    else:
        uid_result = transport.run(["id", "-u"], timeout=10)
        if not uid_result.ok: raise AgentError(f"could not determine uid on {host.name}: {uid_result.stderr.strip()}")
        uid = uid_result.stdout.strip()
        # RunAtLoad is false in the plist, so bootstrap only loads it into launchd
        # (visible to launchctl/service.status) -- it does not start anything.
        # "already bootstrapped" from a prior setup is not an error here.
        bootstrap_result = transport.run(["launchctl", "bootstrap", f"gui/{uid}", rendered["unit_path"]], timeout=15)
        if not bootstrap_result.ok and "already bootstrapped" not in (bootstrap_result.stderr or "").lower():
            raise AgentError(f"launchctl bootstrap failed on {host.name}: {bootstrap_result.stderr.strip()}")
    return {"host": host.name, "wrote_prompt": wrote_prompt, "prompt_path": rendered["prompt_path"],
            "run_script_path": rendered["run_script_path"], "unit_path": rendered["unit_path"],
            "unit_name": rendered["unit_name"], "runtime": rendered["runtime"], "runtime_verified": rendered["runtime_verified"],
            "init_system": init_system}


class AgentStore:
    """Which Standing Agents apx has created, and where -- mirrors NodeStore/
    GrantStore's JSON-overlay pattern. Control (start/stop/restart/status) stays
    with the existing service.* actions; this only tracks provenance."""

    def __init__(self, config_path: Path):
        self.path = config_path.with_suffix(".agents.json")
        self._data = self._load()

    def _load(self) -> dict[str, Any]:
        empty = {"agents": {}}
        if not self.path.exists(): return empty
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
            for key in empty: data.setdefault(key, {})
            return data
        except (OSError, json.JSONDecodeError):
            return empty

    def _save(self) -> None: atomic_write(self.path, json.dumps(self._data, indent=2) + "\n")

    def record(self, name: str, *, host: str, unit_name: str, repo: str, runtime: str, model: str, effort: str,
               state_dir: str, run_script_path: str, prompt_path: str, unit_path: str, created_by: str | None) -> dict[str, Any]:
        entry = {"name": name, "host": host, "unit_name": unit_name, "repo": repo, "runtime": runtime, "model": model, "effort": effort,
                  "state_dir": state_dir, "run_script_path": run_script_path, "prompt_path": prompt_path,
                  "unit_path": unit_path, "created_at": _now(), "created_by": created_by}
        self._data["agents"][name] = entry
        self._save()
        return entry

    def get(self, name: str) -> dict[str, Any]:
        try: return self._data["agents"][name]
        except KeyError as error: raise AgentError(f"unknown agent {name!r}") from error

    def list(self, *, host: str | None = None) -> list[dict[str, Any]]:
        values = self._data["agents"].values()
        if host: values = [a for a in values if a["host"] == host]
        return sorted(values, key=lambda a: a["created_at"])

    def remove(self, name: str) -> dict[str, Any]:
        entry = self.get(name)
        del self._data["agents"][name]
        self._save()
        return entry
