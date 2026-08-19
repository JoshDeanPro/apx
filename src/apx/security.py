# SPDX-License-Identifier: MIT
"""Fast, local-only security and privacy checks.

These checks reduce accidental exposure; they are not a sandbox or a substitute
for OS permissions/process isolation.
"""
from __future__ import annotations

import os
import stat
from pathlib import Path
from typing import Any

from .config import apx_home, default_config_path, load_document, state_files


_SECRET_MARKERS = ("token", "secret", "password", "passwd", "api_key", "apikey", "private_key", "client_secret", "access_token", "refresh_token", "cookie")


def _finding(severity: str, code: str, message: str, fix: str) -> dict[str, str]:
    return {"severity": severity, "code": code, "message": message, "next_action": fix}


def _contains_secret_key(value: Any, path: str = "") -> list[str]:
    found: list[str] = []
    if isinstance(value, dict):
        for key, child in value.items():
            lowered = str(key).lower()
            if any(marker in lowered for marker in _SECRET_MARKERS) and not lowered.endswith(("_id", "_ref")):
                if child not in (None, "", False, (), []):
                    found.append(f"{path}.{key}".strip("."))
            found.extend(_contains_secret_key(child, f"{path}.{key}".strip(".")))
    elif isinstance(value, list):
        for index, child in enumerate(value):
            found.extend(_contains_secret_key(child, f"{path}[{index}]"))
    return found


def check(config_path: str | Path | None = None) -> dict[str, Any]:
    """Inspect local exposure without connecting to servers or resolving secrets."""
    findings: list[dict[str, str]] = []
    try:
        path, document = load_document(config_path)
    except FileNotFoundError:
        path = Path(config_path).expanduser() if config_path else default_config_path()
        document = {}
        findings.append(_finding("WARN", "config_missing", "APX configuration is not present.", "Run `apx init` or provide --config."))
    except Exception:
        path = Path(config_path).expanduser() if config_path else default_config_path()
        document = {}
        findings.append(_finding("FAIL", "config_unreadable", "APX configuration could not be read.", "Fix the configuration permissions or syntax."))

    for candidate in (path, *state_files(path)):
        if not candidate.exists():
            continue
        try:
            mode = stat.S_IMODE(candidate.stat().st_mode)
            if mode & 0o077:
                findings.append(_finding("WARN", "state_permissions", f"APX state file {candidate.name} is readable by group or others.", f"Run `chmod 700 {candidate.parent}` and `chmod 600 {candidate.name}`."))
        except OSError:
            findings.append(_finding("WARN", "state_permissions_unknown", f"Could not inspect permissions for {candidate.name}.", "Inspect the APX state directory permissions."))

    secret_paths = _contains_secret_key(document)
    credentials = document.get("credentials", {}) if isinstance(document, dict) else {}
    if isinstance(credentials, dict):
        for name, value in credentials.items():
            if isinstance(value, dict):
                unexpected = set(value) - {"kind", "provider", "source", "reference", "scopes", "description", "groups", "tags", "api_family", "api_version", "owner"}
                secret_paths.extend(f"credentials.{name}.{key}" for key in sorted(unexpected) if value.get(key) not in (None, "", False, (), []))
    if secret_paths:
        findings.append(_finding("FAIL", "secret_in_config", "Secret-looking values are stored in ordinary APX configuration.", "Move them to a configured credential backend; only store references in config."))

    for index, host in enumerate(document.get("hosts", ()) if isinstance(document, dict) else ()):
        if not isinstance(host, dict):
            continue
        target = str(host.get("target", ""))
        if target.startswith("http://") and "localhost" not in target and "127.0.0.1" not in target and "::1" not in target:
            findings.append(_finding("FAIL", "plaintext_remote", f"Configured host {index + 1} uses plaintext HTTP.", "Use HTTPS or explicitly restrict the endpoint to loopback."))

    server = document.get("server", {}) if isinstance(document, dict) else {}
    if isinstance(server, dict) and str(server.get("host", "127.0.0.1")) not in {"127.0.0.1", "localhost", "::1"}:
        findings.append(_finding("WARN", "public_bind", "APX server is configured beyond loopback.", "Bind to loopback unless authenticated remote access is explicitly required."))

    plugins = document.get("plugins", {}) if isinstance(document, dict) else {}
    if isinstance(plugins, dict):
        enabled = sorted(name for name, value in plugins.items() if isinstance(value, dict) and value.get("enabled"))
        if enabled:
            findings.append(_finding("WARN", "plugins_enabled", f"Optional plugins enabled: {', '.join(enabled)}.", "Review each plugin's source, credentials, and required permissions."))

    if os.environ.get("APX_DEBUG"):
        findings.append(_finding("WARN", "debug_enabled", "APX debug mode is enabled.", "Disable APX_DEBUG outside local troubleshooting."))

    return {"ok": not any(item["severity"] == "FAIL" for item in findings), "config": str(path), "checks": findings, "model": "local checks reduce accidental disclosure; they do not provide process or OS sandboxing"}
