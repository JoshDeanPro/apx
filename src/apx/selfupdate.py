# SPDX-License-Identifier: MPL-2.0
"""`apx update` -- two installation kinds, two meanings, never blurred.

**Development checkout.** The package is imported out of a git working tree that
carries APX's own source layout (an editable install). Updating means a
fast-forward-only `git pull`, refused outright when the tree is dirty or the
history is not a fast-forward, so it can never discard or rewrite work. A
reinstall runs only when `pyproject.toml` itself changed, i.e. when dependencies
moved -- source-only changes are already live for the next process.

**Installed runtime.** A wheel in a venv, with no checkout anywhere near it. This
is the normal model on a server, and updating it means installing a newer wheel
over it. Where that wheel comes from is *configured*, never guessed: `--from`, or
`$APX_UPDATE_SOURCE`, or `[update] source` in the config. APX does not phone a
hosted service to find out whether it is out of date -- an installation that was
never told where its updates come from says so instead of reaching out.

Local state (`$APX_HOME`) is never touched by either path: updating the software
and owning the machine's configuration are separate concerns, and the config lives
outside both the checkout and the venv precisely so an update cannot reach it.
"""
from __future__ import annotations

import os
import subprocess
import sys
import sysconfig
import tempfile
from pathlib import Path
from typing import Any

from . import __version__


class UpdateError(RuntimeError): pass


def _repo_root() -> Path:
    # src/apx/selfupdate.py -> src/apx -> src -> repo root
    return Path(__file__).resolve().parents[2]


def _is_development_checkout() -> bool:
    """`_repo_root()` is derived from this file's own location, so the question is
    only whether apx is being imported out of its git working tree or out of a venv."""
    root = _repo_root()
    return (root/".git").exists() and (root/"pyproject.toml").exists()


def installation() -> dict[str, Any]:
    """Where this apx came from, decided by what is actually on disk."""
    root = _repo_root()
    if _is_development_checkout():
        return {"kind": "development", "root": str(root), "python": sys.executable}
    return {"kind": "installed", "prefix": sys.prefix, "python": sys.executable,
            "entrypoint": str(Path(sysconfig.get_path("scripts"))/"apx")}


def _run(argv: list[str], cwd: Path | None = None, timeout: int = 30) -> tuple[bool, str, str]:
    try:
        result = subprocess.run(argv, cwd=cwd, capture_output=True, text=True, timeout=timeout)
        return result.returncode == 0, result.stdout.strip(), result.stderr.strip()
    except (OSError, subprocess.TimeoutExpired) as error:
        return False, "", str(error)


def version_info() -> dict[str, Any]:
    info: dict[str, Any] = {"version": __version__, **installation(), "git": None}
    root = _repo_root()
    if (root/".git").exists():
        commit_ok, commit, _ = _run(["git", "rev-parse", "--short", "HEAD"], root)
        clean_ok, dirty, _ = _run(["git", "status", "--porcelain"], root)
        branch_ok, branch, _ = _run(["git", "rev-parse", "--abbrev-ref", "HEAD"], root)
        info["git"] = {"commit": commit if commit_ok else None, "branch": branch if branch_ok else None,
                       "dirty": bool(dirty) if clean_ok else None}
    return info


def update_source(explicit: str | None = None, config: dict | None = None) -> str | None:
    """A wheel/sdist path, a directory, a URL, or a pip requirement -- whatever this
    installation was told to update from. Never inferred from a hosted service."""
    if explicit: return explicit
    from_environment = os.environ.get("APX_UPDATE_SOURCE")
    if from_environment: return from_environment
    return ((config or {}).get("update") or {}).get("source")


def check_for_updates(*, source: str | None = None, config: dict | None = None) -> dict[str, Any]:
    """Read-only. On a checkout this fetches (touching only remote-tracking refs,
    never the working tree) and reports how far behind upstream we are."""
    where = installation()
    if where["kind"] != "development":
        configured = update_source(source, config)
        return {"kind": "installed", "current": __version__, "source": configured,
                "update_available": None,
                "note": "install the configured source to update"
                if configured else "no update source configured: set [update] source, $APX_UPDATE_SOURCE, or pass --from"}
    root = _repo_root()
    fetch_ok, _, fetch_err = _run(["git", "fetch", "--quiet"], root, timeout=60)
    if not fetch_ok: return {"kind": "development", "update_available": False, "error": fetch_err or "git fetch failed"}
    head_ok, head, _ = _run(["git", "rev-parse", "HEAD"], root)
    upstream_ok, upstream, upstream_err = _run(["git", "rev-parse", "@{u}"], root)
    if not (head_ok and upstream_ok):
        return {"kind": "development", "update_available": False, "error": upstream_err or "no upstream branch configured"}
    count_ok, count, _ = _run(["git", "rev-list", "--count", f"{head}..{upstream}"], root)
    behind = int(count) if count_ok and count.isdigit() else 0
    return {"kind": "development", "update_available": behind > 0, "commits_behind": behind,
            "current": head[:8], "upstream": upstream[:8]}


def _update_development(*, reinstall: bool) -> dict[str, Any]:
    root = _repo_root()
    dirty_ok, dirty, dirty_err = _run(["git", "status", "--porcelain"], root)
    if not dirty_ok: raise UpdateError(f"could not verify the working tree is clean, refusing to update: {dirty_err or 'git status failed'}")
    if dirty: raise UpdateError("working tree has uncommitted changes; commit or stash before updating")
    before_ok, before_sha, _ = _run(["git", "rev-parse", "--short", "HEAD"], root)
    pyproject = root/"pyproject.toml"
    before_deps = pyproject.read_text(encoding="utf-8") if pyproject.exists() else ""
    pull_ok, pull_out, pull_err = _run(["git", "pull", "--ff-only"], root, timeout=60)
    if not pull_ok: raise UpdateError(pull_err or pull_out or "git pull --ff-only failed (not a fast-forward?)")
    after_ok, after_sha, _ = _run(["git", "rev-parse", "--short", "HEAD"], root)
    after_deps = pyproject.read_text(encoding="utf-8") if pyproject.exists() else ""
    reinstalled = False
    if reinstall and before_deps != after_deps:
        pip_ok, pip_out, pip_err = _run([sys.executable, "-m", "pip", "install", "-e", "."], root, timeout=300)
        if not pip_ok: raise UpdateError(f"pulled to {after_sha} but reinstall failed: {pip_err or pip_out}")
        reinstalled = True
    return {"kind": "development", "updated": before_sha != after_sha, "before": before_sha,
            "after": after_sha, "reinstalled": reinstalled, "pull_output": pull_out}


def _update_installed(source: str) -> dict[str, Any]:
    before = __version__
    pip_ok, pip_out, pip_err = _run([sys.executable, "-m", "pip", "install", "--upgrade", source], timeout=600)
    if not pip_ok: raise UpdateError(f"installing {source} failed: {pip_err or pip_out}")
    after = _installed_version()
    return {"kind": "installed", "updated": after != before, "before": before, "after": after, "source": source}


def _installed_version() -> str:
    """Read the version back from a fresh interpreter: this process still holds the
    pre-update module, so `apx.__version__` here would report the old number."""
    ok, out, _ = _run([sys.executable, "-c", "import importlib.metadata as m; print(m.version('apx'))"])
    return out if ok else __version__


def apply_update(*, reinstall: bool = True, source: str | None = None, config: dict | None = None) -> dict[str, Any]:
    if installation()["kind"] == "development":
        return _update_development(reinstall=reinstall)
    configured = update_source(source, config)
    if not configured:
        raise UpdateError(
            "no update source configured for this installation: pass `apx update --from <wheel|sdist|url|requirement>`, "
            "set $APX_UPDATE_SOURCE, or add `[update] source = \"...\"` to the config"
        )
    return _update_installed(configured)


# ---------------------------------------------------------------- pushing to a node

def build_wheel(destination: Path | None = None) -> Path:
    """Build a wheel from this checkout. The unit APX ships to another machine."""
    if not _is_development_checkout():
        raise UpdateError("a wheel can only be built from a development checkout")
    output = Path(destination) if destination else Path(tempfile.mkdtemp(prefix="apx-wheel-"))
    output.mkdir(parents=True, exist_ok=True)
    ok, out, err = _run([sys.executable, "-m", "build", "--wheel", "--outdir", str(output)], _repo_root(), timeout=600)
    if not ok: raise UpdateError(f"wheel build failed: {err or out}")
    wheels = sorted(output.glob("apx-*.whl"), key=lambda path: path.stat().st_mtime)
    if not wheels: raise UpdateError(f"wheel build reported success but produced nothing in {output}")
    return wheels[-1]


def push_to_host(host, *, wheel: Path | None = None, timeout: int = 600) -> dict[str, Any]:
    """Install this source tree's wheel onto another Node over its own configured
    transport. No package index, no release server, no hosted installer: the fleet
    updates itself with the connectivity it already has.

    Deliberately not implemented for the local node -- updating the machine you are
    standing on is `apx update`, and having two paths do the same thing is how you
    get two subtly different results."""
    from .transports import TransportError, transport_for

    if host.is_self:
        raise UpdateError(f"{host.name} is this machine; use `apx update` for the local installation")
    built = Path(wheel) if wheel else build_wheel()
    transport = transport_for(host)
    remote_path = f"/tmp/{built.name}"
    if not host.target:
        raise UpdateError(f"host {host.name!r} has no SSH target to copy a wheel to")
    ok, out, err = _run(["scp", "-q", "-o", "BatchMode=yes", str(built), f"{host.target}:{remote_path}"], timeout=timeout)
    if not ok: raise UpdateError(f"could not copy the wheel to {host.name}: {err or out}")
    try:
        python = _remote_python(transport)
        result = transport.run([python, "-m", "pip", "install", "--upgrade", "--quiet", remote_path], timeout=timeout)
        if not result.ok:
            raise UpdateError(f"pip install on {host.name} failed: {result.stderr.strip() or result.stdout.strip()}")
        verify = transport.run([python, "-c", "import importlib.metadata as m; print(m.version('apx'))"], timeout=60)
        installed_version = verify.stdout.strip() if verify.ok else None
    except TransportError as error:
        raise UpdateError(f"{host.name}: {error}") from error
    finally:
        try: transport.run(["rm", "-f", remote_path], timeout=30)
        except TransportError: pass
    return {"host": host.name, "wheel": built.name, "version": installed_version,
            "matches_source": installed_version == __version__}


def _remote_python(transport) -> str:
    """The interpreter that owns the remote apx entrypoint, so the wheel lands in the
    venv that actually serves `apx` rather than in whatever python is first on PATH."""
    probe = transport.run(
        ["sh", "-c", "p=$(command -v apx) || exit 1; d=$(dirname \"$(readlink -f \"$p\")\"); "
                     "[ -x \"$d/python\" ] && echo \"$d/python\" || command -v python3"],
        timeout=30,
    )
    resolved = probe.stdout.strip() if probe.ok else ""
    if not resolved: raise UpdateError("could not find a python interpreter on the remote node")
    return resolved
