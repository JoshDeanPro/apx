"""Mints the HS256 identity assertions AXP's own auth_openpower.py verifies.

This is the OpenPower side of a symmetric-secret protocol that already exists
and is documented on the AXP side (LOCALCLOUD's auth_openpower.py /
docs/identity-and-auth.md): AXP authenticates a linked human or agent by
verifying a short-lived HS256 JWT against a shared secret, then checks
revocation status against `/v1/agents/{principal_id}/status`. This module is
the minimal, stdlib-only counterpart that issues that token and answers that
status check -- deliberately no third-party JWT dependency, mirroring AXP's
own reasoning (RFC 7519 verification via vetted stdlib crypto primitives is
not "rolling your own crypto"; asymmetric verification is a later milestone
on both sides).

OpenPower only ever authenticates who a principal is. What that principal may
do locally is entirely AXP's own policy decision -- this module never expresses
a permission, only an identity assertion.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import time
from typing import Any


def _b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def mint_jwt_hs256(
    *,
    subject: str,
    principal_type: str,
    secret: str,
    issuer: str = "openpower.one",
    audience: str = "axp",
    ttl_seconds: int,
) -> tuple[str, int]:
    """Returns (token, exp_unix). `secret` must be non-empty -- callers check
    OPENPOWER_AXP_SHARED_SECRET is configured before calling this."""
    if not secret:
        raise ValueError("mint_jwt_hs256 requires a non-empty secret")
    now = int(time.time())
    exp = now + ttl_seconds
    header = {"alg": "HS256", "typ": "JWT"}
    claims: dict[str, Any] = {
        "sub": subject,
        "principal_type": principal_type,
        "iss": issuer,
        "aud": audience,
        "iat": now,
        "exp": exp,
    }
    header_b64 = _b64url(json.dumps(header, separators=(",", ":")).encode())
    payload_b64 = _b64url(json.dumps(claims, separators=(",", ":")).encode())
    signing_input = f"{header_b64}.{payload_b64}".encode()
    signature = hmac.new(secret.encode(), signing_input, hashlib.sha256).digest()
    token = f"{header_b64}.{payload_b64}.{_b64url(signature)}"
    return token, exp
