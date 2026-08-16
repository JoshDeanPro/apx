# SPDX-License-Identifier: MPL-2.0
"""Compatibility shim for the LocalCloud extraction.

LocalCloud is owned by OpenPower now. New code should import from
`openpower.localcloud` instead of `apx.localcloud`.
"""
from openpower.localcloud.vault import (  # noqa: F401
    LOCALCLOUD_DIR,
    PEERS_FILE,
    VAULT_FILE,
    _decrypt_payload,
    _encrypt_payload,
    _ensure_storage,
    _get_encryption_key,
    _read_peers,
    _read_vault,
    _write_peers,
    _write_vault,
    localcloud_get,
    localcloud_set,
    localcloud_status,
    localcloud_sync_peer,
)

__all__ = [
    "localcloud_get",
    "localcloud_set",
    "localcloud_status",
    "localcloud_sync_peer",
]
