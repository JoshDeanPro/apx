# SPDX-License-Identifier: MPL-2.0
"""Update apx from its own git checkout without a separate reinstall-and-restart
dance. apx is normally run from an editable install (`pip install -e .`), so a
plain fast-forward `git pull` on the source tree is immediately visible to the
NEXT process that imports this package -- `apx mcp` is spawned fresh per client
session, and the CLI is spawned fresh per invocation, so there is no long-lived
process holding stale bytecode to restart in the common case. The only extra step
needed is a `pip install -e .` re-run, and only when `pyproject.toml` itself
changed (new/changed dependencies) -- not on every source-only change.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

from . import __version__


class UpdateError(RuntimeError): pass


def _repo_root() -> Path:
    # src/apx/selfupdate.py -> src/apx -> src -> repo root
    return Path(__file__).resolve().parents[2]


def _is_managed_venv() -> bool:
    """True for a machine installed via install.sh's managed venv (a pip-installed
    wheel with no .git anywhere near it -- home/vps, not this development checkout)."""
    return "openpower/runtimes" in str(Path(sys.prefix))


def _download_installer() -> Path:
    base_url = os.environ.get("OPENPOWER_DOWNLOAD_BASE", "https://openpower.dev")
    descriptor, name = tempfile.mkstemp(prefix="apx-update-", suffix=".sh")
    target = Path(name)
    try:
        request = urllib.request.Request(f"{base_url}/install", headers={"User-Agent": f"apx/{__version__}"})
        with urllib.request.urlopen(request, timeout=30) as response:
            data = response.read(64 * 1024 + 1)
        if len(data) > 64 * 1024: raise UpdateError("installer exceeded the expected size limit")
        with os.fdopen(descriptor, "wb") as stream: stream.write(data)
    except (OSError, urllib.error.URLError) as error:
        try: os.close(descriptor)
        except OSError: pass
        target.unlink(missing_ok=True)
        raise UpdateError(f"could not download the installer: {error}") from error
    target.chmod(0o700)
    return target


def _run_managed_venv_update() -> dict[str, Any]:
    """Managed-venv installs (home/vps -- see _is_managed_venv) have no git checkout
    to `git pull`; "update" means re-running the same installer that set them up,
    which fetches fresh apx/openpower-cli wheels and rebuilds the venv in place.
    Mirrors what the now-retired `op update` did, just invoked from `apx update`."""
    explicit = os.environ.get("OPENPOWER_INSTALLER")
    installer = Path(explicit) if explicit else _download_installer()
    downloaded = not explicit
    try:
        if not installer.exists(): raise UpdateError(f"installer not found at {installer}")
        result = subprocess.run([str(installer), "--update", "--json"], capture_output=True, text=True, timeout=180)
        try: payload = json.loads(result.stdout.strip().splitlines()[-1]) if result.stdout.strip() else {}
        except (json.JSONDecodeError, IndexError): payload = {}
        if result.returncode != 0 or not payload.get("ok", result.returncode == 0):
            raise UpdateError(payload.get("error") or result.stderr.strip() or "installer --update failed")
        return {"updated": True, "method": "managed-venv", **payload}
    except subprocess.TimeoutExpired as error:
        raise UpdateError(f"installer timed out: {error}") from error
    finally:
        if downloaded: installer.unlink(missing_ok=True)


def _run(argv: list[str], cwd: Path, timeout: int = 30) -> tuple[bool, str, str]:
    try:
        result = subprocess.run(argv, cwd=cwd, capture_output=True, text=True, timeout=timeout)
        return result.returncode == 0, result.stdout.strip(), result.stderr.strip()
    except (OSError, subprocess.TimeoutExpired) as error:
        return False, "", str(error)


def version_info() -> dict[str, Any]:
    root = _repo_root()
    info: dict[str, Any] = {"version": __version__, "repo": str(root), "git": None}
    if (root/".git").exists():
        commit_ok, commit, _ = _run(["git", "rev-parse", "--short", "HEAD"], root)
        clean_ok, dirty, _ = _run(["git", "status", "--porcelain"], root)
        branch_ok, branch, _ = _run(["git", "rev-parse", "--abbrev-ref", "HEAD"], root)
        info["git"] = {"commit": commit if commit_ok else None, "branch": branch if branch_ok else None,
                        "dirty": bool(dirty) if clean_ok else None}
    return info


def check_for_updates() -> dict[str, Any]:
    """Read-only: fetches (touches only .git's remote-tracking refs, never the
    working tree) and reports how far behind the tracked upstream branch is."""
    root = _repo_root()
    if not (root/".git").exists():
        if not _is_managed_venv(): return {"git_repo": False, "update_available": False}
        try:
            base_url = os.environ.get("OPENPOWER_DOWNLOAD_BASE", "https://openpower.dev")
            request = urllib.request.Request(f"{base_url}/downloads/foundation-manifest.json", headers={"User-Agent": f"apx/{__version__}"})
            with urllib.request.urlopen(request, timeout=15) as response: manifest = json.loads(response.read())
            latest = manifest["apx_version"]
        except (OSError, urllib.error.URLError, KeyError, json.JSONDecodeError) as error:
            return {"git_repo": False, "managed_venv": True, "update_available": False, "error": str(error)}
        return {"git_repo": False, "managed_venv": True, "update_available": latest != __version__, "current": __version__, "latest": latest}
    fetch_ok, _, fetch_err = _run(["git", "fetch", "--quiet"], root)
    if not fetch_ok: return {"git_repo": True, "update_available": False, "error": fetch_err or "git fetch failed"}
    head_ok, head, _ = _run(["git", "rev-parse", "HEAD"], root)
    upstream_ok, upstream, upstream_err = _run(["git", "rev-parse", "@{u}"], root)
    if not (head_ok and upstream_ok):
        return {"git_repo": True, "update_available": False, "error": upstream_err or "no upstream branch configured"}
    count_ok, count, _ = _run(["git", "rev-list", "--count", f"{head}..{upstream}"], root)
    behind = int(count) if count_ok and count.isdigit() else 0
    return {"git_repo": True, "update_available": behind > 0, "commits_behind": behind,
            "current": head[:8], "upstream": upstream[:8]}


def apply_update(*, reinstall: bool = True) -> dict[str, Any]:
    """Fast-forward-only pull -- refuses to run with local uncommitted changes or a
    non-fast-forward history, so it can never silently discard or rewrite work.
    Reinstalls only if pyproject.toml's own text changed."""
    root = _repo_root()
    if not (root/".git").exists():
        if _is_managed_venv(): return _run_managed_venv_update()
        raise UpdateError(f"{root} is not a git checkout and does not look like a managed-venv install; nothing to update")
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
        pip_ok, pip_out, pip_err = _run([sys.executable, "-m", "pip", "install", "-e", "."], root, timeout=180)
        if not pip_ok: raise UpdateError(f"pulled to {after_sha} but reinstall failed: {pip_err or pip_out}")
        reinstalled = True
    return {"updated": before_sha != after_sha, "before": before_sha, "after": after_sha,
            "reinstalled": reinstalled, "pull_output": pull_out}
