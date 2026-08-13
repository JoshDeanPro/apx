from __future__ import annotations

from dataclasses import dataclass
from fnmatch import fnmatchcase
from typing import Callable

from .axp import Event

EventListener = Callable[[Event], None]


@dataclass(frozen=True)
class Subscription:
    pattern: str
    listener: EventListener
    owner: str = "core"


class EventRouter:
    """Small synchronous in-process router; listeners never require infrastructure."""

    def __init__(self):
        self._subscriptions: list[Subscription] = []
        self._history: list[Event] = []
        self._errors: list[dict[str,str]] = []

    def subscribe(self, pattern: str, listener: EventListener, *, owner: str = "core") -> Subscription:
        subscription=Subscription(pattern,listener,owner)
        self._subscriptions.append(subscription)
        return subscription

    def emit(self, event: Event) -> Event:
        self._history.append(event)
        for subscription in tuple(self._subscriptions):
            if fnmatchcase(event.name,subscription.pattern):
                try: subscription.listener(event)
                except Exception as error:
                    self._errors.append({"event":event.name,"owner":subscription.owner,"error":str(error)})
        return event

    @property
    def history(self) -> tuple[Event,...]: return tuple(self._history)
    @property
    def errors(self) -> tuple[dict[str,str],...]: return tuple(self._errors)

