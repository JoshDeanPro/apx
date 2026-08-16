# SPDX-License-Identifier: MPL-2.0
"""Cryptographic signature and verifiable digest utilities for APX ActionReceipts."""
from __future__ import annotations

import hashlib
import hmac
import json
import os
import secrets
from pathlib import Path
from typing import Any

from .config import apx_home


def canonical_json_bytes(data: Any) -> bytes:
    """Deterministic, canonical JSON byte representation (RFC 8785 subset)."""
    return json.dumps(data, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def get_node_key(home_path: Path | None = None) -> tuple[bytes, str]:
    """Retrieve or generate the local node's private signing key and key identifier."""
    base = home_path or apx_home()
    key_file = base / "node.key"
    if key_file.exists():
        raw = key_file.read_bytes().strip()
        if len(raw) >= 32:
            key_id = hashlib.sha256(raw).hexdigest()[:16]
            return raw, key_id

    # Generate persistent random 32-byte secret key
    try:
        base.mkdir(parents=True, exist_ok=True)
        secret = secrets.token_bytes(32)
        key_file.write_bytes(secret)
        key_file.chmod(0o600)
        key_id = hashlib.sha256(secret).hexdigest()[:16]
        return secret, key_id
    except OSError:
        ephemeral = secrets.token_bytes(32)
        return ephemeral, "ephemeral"


def compute_receipt_digest(data: dict[str, Any]) -> str:
    """Compute deterministic SHA-256 hash over receipt payload (excluding signatures and metadata)."""
    clean = {k: v for k, v in data.items() if k not in ("signature", "digest", "key_id", "verified", "signer_node")}
    return hashlib.sha256(canonical_json_bytes(clean)).hexdigest()


def sign_receipt_dict(receipt_dict: dict[str, Any], node_name: str = "local", home_path: Path | None = None) -> dict[str, Any]:
    """Sign an action receipt with the local node key, attaching digest and cryptographic proof."""
    key, key_id = get_node_key(home_path)
    digest = compute_receipt_digest(receipt_dict)
    sig = hmac.new(key, digest.encode("utf-8"), hashlib.sha256).hexdigest()
    out = dict(receipt_dict)
    out["digest"] = digest
    out["signature"] = f"apx-hmac-sha256:{sig}"
    out["signer_node"] = node_name
    out["key_id"] = key_id
    return out


def verify_receipt_dict(receipt_dict: dict[str, Any], home_path: Path | None = None) -> bool:
    """Verify that a receipt's signature matches its digest and contents."""
    sig = receipt_dict.get("signature")
    digest = receipt_dict.get("digest")
    if not sig or not digest:
        return False
    
    expected_digest = compute_receipt_digest(receipt_dict)
    if not hmac.compare_digest(digest, expected_digest):
        return False

    key, _ = get_node_key(home_path)
    expected_sig = f"apx-hmac-sha256:{hmac.new(key, digest.encode('utf-8'), hashlib.sha256).hexdigest()}"
    return hmac.compare_digest(sig, expected_sig)
