"""In-process rate limiting.

Simple per-user sliding-window limiter held in a module-level dict. This is
intentionally NOT a distributed rate limiter: it works only within a single
running process's memory. That is an accepted limitation for V1 — the
service is deployed as a single systemd-managed uvicorn process behind
Caddy. If this service is ever scaled to multiple processes/instances,
this must be replaced with a shared store (e.g. Redis) or the limiter will
under-count and allow `N * process_count` requests through instead of `N`.
"""
from __future__ import annotations

import time
import uuid
from collections import defaultdict, deque
from typing import Hashable

from fastapi import Depends, HTTPException, Request, status

from .auth import AuthenticatedUser, get_current_user
from .config import get_settings

# action_name -> key (user_id or client IP) -> deque[timestamps]
_hits: dict[str, dict[Hashable, deque[float]]] = defaultdict(lambda: defaultdict(deque))


def _check_and_record(action: str, key: Hashable, *, max_requests: int, window_seconds: int) -> None:
    now = time.monotonic()
    bucket = _hits[action][key]
    cutoff = now - window_seconds
    while bucket and bucket[0] < cutoff:
        bucket.popleft()
    if len(bucket) >= max_requests:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=f"Rate limit exceeded for {action}; try again later",
        )
    bucket.append(now)


def reset_rate_limits() -> None:
    """Test helper: clear all in-memory rate-limit state between tests."""
    _hits.clear()


def rate_limited(action: str):
    """Dependency factory: enforces a per-user sliding-window limit for `action`."""

    async def _dependency(user: AuthenticatedUser = Depends(get_current_user)) -> AuthenticatedUser:
        settings = get_settings()
        _check_and_record(
            action,
            user.id,
            max_requests=settings.rate_limit_max,
            window_seconds=settings.rate_limit_window_seconds,
        )
        return user

    return _dependency


def rate_limited_by_ip(action: str, *, max_requests: int | None = None, window_seconds: int | None = None):
    """Same limiter, keyed by client IP instead of an authenticated user --
    for the device-link endpoints, which are unauthenticated by design
    (device_code/user_code are the credential)."""

    async def _dependency(request: Request) -> None:
        settings = get_settings()
        _check_and_record(
            action,
            request.client.host if request.client else "unknown",
            max_requests=max_requests or settings.rate_limit_max,
            window_seconds=window_seconds or settings.rate_limit_window_seconds,
        )

    return _dependency
