# SPDX-License-Identifier: MIT
from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Protocol, Any


@dataclass(frozen=True)
class AdapterMetadata:
    name: str
    version: str
    description: str
    kinds: tuple[str,...]
    optional_dependencies: tuple[str,...] = ()

    def to_dict(self): return asdict(self)


class Adapter(Protocol):
    metadata: AdapterMetadata
    def health(self) -> dict[str,Any]: ...
