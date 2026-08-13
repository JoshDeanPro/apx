# SPDX-License-Identifier: MPL-2.0
"""Shared component health vocabulary consumed by `doctor`."""
from __future__ import annotations
from dataclasses import asdict,dataclass,field
from typing import Any

HEALTH_STATES=("healthy","degraded","unavailable","misconfigured","incompatible","authentication_required","update_required")


@dataclass(frozen=True)
class ComponentHealth:
    component: str
    status: str
    detail: str=""
    capabilities: tuple[str,...]=()
    metadata: dict[str,Any]=field(default_factory=dict)
    def __post_init__(self):
        if self.status not in HEALTH_STATES: raise ValueError(f"invalid health status {self.status!r}")
    @property
    def ok(self)->bool: return self.status=="healthy"
    def to_dict(self)->dict[str,Any]: return asdict(self)
