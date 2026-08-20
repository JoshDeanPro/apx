# SPDX-License-Identifier: MIT
"""Small shared filesystem safety primitives."""
from __future__ import annotations

import os
import tempfile
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator


_PRIVATE_NAMES = frozenset({
    ".env", ".ssh", ".aws", ".azure", ".gcloud", ".kube", ".docker",
    "keychains", "login.keychain-db", "cookies", "cookies.sqlite",
})


def normalized(path: str | Path) -> Path:
    """Canonicalize a path and reject common credential/private-data targets."""
    target = Path(path).expanduser().resolve(strict=False)
    lowered_parts = {part.lower() for part in target.parts}
    if lowered_parts & _PRIVATE_NAMES or target.name.lower() in {"id_rsa", "id_ed25519", "known_hosts"}:
        raise ValueError("path targets a protected credential or private-data location")
    if target.suffix.lower() in {".pem", ".key", ".p12", ".pfx"}:
        raise ValueError("path targets protected key material")
    return target


def bounded_read(path: str | Path, *, max_bytes: int=1024*1024) -> bytes:
    target=normalized(path)
    with target.open("rb") as stream:
        value=stream.read(max_bytes+1)
    if len(value)>max_bytes: raise ValueError(f"{target} exceeds {max_bytes} bytes")
    return value


@contextmanager
def file_lock(path: str | Path) -> Iterator[None]:
    lock=normalized(path).with_suffix(normalized(path).suffix+".lock"); lock.parent.mkdir(parents=True,exist_ok=True)
    descriptor=os.open(lock,os.O_CREAT|os.O_RDWR,0o600)
    try:
        if os.name=="posix":
            import fcntl
            fcntl.flock(descriptor,fcntl.LOCK_EX)
        yield
    finally:
        if os.name=="posix": fcntl.flock(descriptor,fcntl.LOCK_UN)
        os.close(descriptor)


def atomic_write(path: str | Path, data: str | bytes, *, mode: int=0o600) -> None:
    target=normalized(path); target.parent.mkdir(parents=True,exist_ok=True)
    payload=data.encode() if isinstance(data,str) else data
    with file_lock(target):
        descriptor,temporary=tempfile.mkstemp(prefix=f".{target.name}.",dir=target.parent)
        try:
            try: os.fchmod(descriptor,mode)
            except OSError: pass
            with os.fdopen(descriptor,"wb") as stream:
                stream.write(payload); stream.flush(); os.fsync(stream.fileno())
            os.replace(temporary,target)
        except Exception:
            try: os.close(descriptor)
            except OSError: pass
            raise
        finally:
            if os.path.exists(temporary):
                try: os.unlink(temporary)
                except OSError: pass

