# SPDX-License-Identifier: MIT
"""Deterministic APX execution instrumentation and reusable procedures."""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
import time
from typing import Any, Callable


class ReasoningRequired(RuntimeError):
    """An executor reached a genuinely ambiguous boundary without taking action."""

    def __init__(self, message: str, *, context: dict[str, Any] | None = None):
        super().__init__(message); self.context=context or {}


class ProcedureFailed(RuntimeError):
    def __init__(self, procedure: str, step: str, code: str, message: str):
        super().__init__(f"procedure {procedure} stopped at {step}: {message}")
        self.procedure=procedure; self.step=step; self.code=code


@dataclass(frozen=True)
class ExecutionRecord:
    action: str
    deterministic: bool
    duration_ms: float
    status: str
    changed: bool | None = None
    adapter: str | None = None
    reasoning_calls: int = 0
    model_calls_avoided: int = 1

    def to_dict(self) -> dict[str, Any]: return asdict(self)


class ExecutionMetrics:
    """Small in-memory counters; no telemetry and no invented token estimates."""

    def __init__(self): self.executed=0; self.escalated=0; self.failed=0; self.total_duration_ms=0.0
    def record(self,value: ExecutionRecord) -> None:
        if value.status=="needs_reasoning": self.escalated+=1
        else: self.executed+=1
        if value.status=="failed": self.failed+=1
        self.total_duration_ms+=value.duration_ms
    def snapshot(self) -> dict[str, Any]:
        total=self.executed+self.escalated
        return {"deterministic_actions":self.executed,"reasoning_escalations":self.escalated,
            "model_calls_avoided":self.executed,"failures":self.failed,
            "average_duration_ms":round(self.total_duration_ms/total,3) if total else 0,
            "estimated_tokens_avoided":None}


class ExecutionPlane:
    """Runs an already-authorized registered handler. It contains no AI client."""

    def __init__(self): self.metrics=ExecutionMetrics()
    def run(self,action,inputs: dict[str,Any]) -> tuple[Any,ExecutionRecord]:
        started=time.monotonic()
        try:
            value=action.handler(**inputs)
        except ReasoningRequired:
            record=ExecutionRecord(action.name,True,round((time.monotonic()-started)*1000,3),"needs_reasoning",model_calls_avoided=0)
            self.metrics.record(record); raise
        except Exception:
            record=ExecutionRecord(action.name,True,round((time.monotonic()-started)*1000,3),"failed",model_calls_avoided=1)
            self.metrics.record(record); raise
        changed=value.get("changed") if isinstance(value,dict) and isinstance(value.get("changed"),bool) else None
        adapter=value.get("adapter") or value.get("manager") if isinstance(value,dict) else None
        record=ExecutionRecord(action.name,True,round((time.monotonic()-started)*1000,3),"completed",changed,adapter)
        self.metrics.record(record); return value,record


@dataclass(frozen=True)
class ProcedureStep:
    action: str
    input: dict[str,Any]=field(default_factory=dict)
    forward: tuple[str,...]=()


@dataclass(frozen=True)
class Procedure:
    id: str
    description: str
    steps: tuple[ProcedureStep,...]
    risk: str="low_change"
    confirmation: str="confirm"


class ProcedureRegistry:
    """Typed, inspectable workflows. Every step re-enters APX policy execution."""

    def __init__(self): self._items: dict[str,Procedure]={}
    def register(self,value: Procedure,available_actions: set[str]) -> None:
        if value.id in self._items: raise ValueError(f"duplicate procedure {value.id}")
        missing=[step.action for step in value.steps if step.action not in available_actions]
        if missing: raise ValueError("procedure references unknown actions: "+", ".join(missing))
        self._items[value.id]=value
    def get(self,name: str) -> Procedure:
        try: return self._items[name]
        except KeyError as error: raise KeyError(f"unknown procedure {name!r}") from error
    def list(self) -> tuple[Procedure,...]: return tuple(self._items.values())
