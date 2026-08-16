from __future__ import annotations

import json
import subprocess
import urllib.error
import urllib.request
import uuid
from pathlib import Path
from typing import Any

HOME = Path.home()

REAL_APX = (
    HOME
    / ".local"
    / "share"
    / "apx"
    / "runtime"
    / "bin"
    / "apx"
)


def _secret(identifier: str) -> str:
    if not REAL_APX.exists():
        raise RuntimeError(
            "APX runtime is unavailable"
        )

    for command in (
        [
            str(REAL_APX),
            "secret",
            "reveal",
            identifier,
        ],
        [
            str(REAL_APX),
            "secret",
            "get",
            identifier,
        ],
    ):
        p = subprocess.run(
            command,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            check=False,
        )

        if p.returncode != 0:
            continue

        raw = p.stdout.strip()

        if not raw:
            continue

        try:
            obj = json.loads(raw)

            if isinstance(obj, str):
                return obj

            if isinstance(obj, dict):
                for key in (
                    "secret",
                    "value",
                    "token",
                    "password",
                ):
                    value = obj.get(key)

                    if isinstance(
                        value,
                        str,
                    ) and value:
                        return value
        except Exception:
            pass

        lines = [
            line.strip()
            for line in raw.splitlines()
            if line.strip()
        ]

        if len(lines) == 1:
            return lines[0]

    raise RuntimeError(
        f"Missing APX secret: {identifier}"
    )


def _json_request(
    url: str,
    *,
    method: str = "POST",
    headers: dict[str, str] | None = None,
    body: dict[str, Any] | None = None,
) -> dict[str, Any]:
    data = None

    request_headers = {
        "Accept": "application/json",
        "User-Agent": "APX/0.8",
    }

    if headers:
        request_headers.update(headers)

    if body is not None:
        data = json.dumps(body).encode()
        request_headers[
            "Content-Type"
        ] = "application/json"

    request = urllib.request.Request(
        url,
        data=data,
        headers=request_headers,
        method=method,
    )

    try:
        with urllib.request.urlopen(
            request,
            timeout=25,
        ) as response:
            raw = response.read().decode(
                errors="replace"
            )

            if not raw:
                return {
                    "ok": True,
                    "status": response.status,
                }

            try:
                value = json.loads(raw)
            except Exception:
                value = {
                    "raw": raw,
                }

            if isinstance(value, dict):
                value.setdefault(
                    "_http_status",
                    response.status,
                )

            return value

    except urllib.error.HTTPError as exc:
        raw = exc.read().decode(
            errors="replace"
        )

        raise RuntimeError(
            f"HTTP {exc.code}: {raw[:900]}"
        )


# ============================================================
# PORKBUN
# ============================================================

PORKBUN_BASE = (
    "https://api.porkbun.com/api/json/v3"
)


def _porkbun_headers() -> dict[str, str]:
    return {
        "X-API-Key": _secret(
            "porkbun_api_key"
        ),
        "X-Secret-API-Key": _secret(
            "porkbun_secret_key"
        ),
    }


def porkbun_domains() -> list[dict[str, Any]]:
    value = _json_request(
        f"{PORKBUN_BASE}/domain/listAll",
        headers=_porkbun_headers(),
        body={},
    )

    domains = value.get(
        "domains",
        [],
    )

    if not isinstance(domains, list):
        domains = []

    return domains


# ============================================================
# PURELYMAIL
# ============================================================

PURELYMAIL_BASE = (
    "https://purelymail.com/api/v0"
)


def _purely_headers() -> dict[str, str]:
    return {
        "Purelymail-Api-Token": _secret(
            "purelymail_credential"
        ),
    }


def _purely(
    endpoint: str,
    body: dict[str, Any] | None = None,
) -> Any:
    value = _json_request(
        f"{PURELYMAIL_BASE}/{endpoint}",
        headers=_purely_headers(),
        body=body or {},
    )

    return value.get(
        "result",
        value,
    )


def purelymail_users() -> list[str]:
    value = _purely(
        "listUser",
        {},
    )

    if isinstance(value, dict):
        users = value.get(
            "users",
            [],
        )

        if isinstance(users, list):
            return [
                str(item)
                for item in users
            ]

    return []


def purelymail_domains() -> list[Any]:
    value = _purely(
        "listDomains",
        {},
    )

    if isinstance(value, dict):
        for key in (
            "domains",
            "domainNames",
        ):
            domains = value.get(key)

            if isinstance(domains, list):
                return domains

    if isinstance(value, list):
        return value

    return []


def purelymail_create_user(
    *,
    local_part: str,
    domain: str,
    password: str,
    send_welcome: bool = True,
    search_indexing: bool = True,
) -> Any:
    return _purely(
        "createUser",
        {
            "userName": local_part,
            "domainName": domain,
            "password": password,
            "enablePasswordReset": True,
            "enableSearchIndexing": (
                search_indexing
            ),
            "sendWelcomeEmail": (
                send_welcome
            ),
        },
    )


def purelymail_delete_user(
    email: str,
) -> Any:
    return _purely(
        "deleteUser",
        {
            "userName": email,
        },
    )


def purelymail_credit() -> Any:
    return _purely(
        "checkAccountCredit",
        {},
    )
