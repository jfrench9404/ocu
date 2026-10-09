"""Event types and a tiny async pub/sub bus.

Sources (notification listeners, navigation, LLMs, clocks...) publish plain
events. They know nothing about pixels or BLE. The HUD pipeline subscribes and
turns events into wire messages.
"""
from __future__ import annotations

import asyncio
import inspect
from collections import defaultdict
from dataclasses import dataclass
from typing import Any, Awaitable, Callable


@dataclass
class Notification:
    app: str            # "call" | "message" | "email" | "calendar" | "ai" | anything
    title: str
    body: str = ""
    ttl_s: int = 6


@dataclass
class NavUpdate:
    maneuver: str       # "left", "slight right", "uturn", "arrive", ... (Mapbox/OSRM style)
    distance_m: float | None
    street: str = ""


@dataclass
class NavEnd:
    pass


@dataclass
class StatusText:
    left: str | None = None
    right: str | None = None


@dataclass
class MainText:
    text: str


@dataclass
class DetailText:
    text: str


@dataclass
class LlmChunk:
    """A streamed piece of an AI answer. Send done=True at the end."""
    text: str
    done: bool = False
    title: str = "AI"


@dataclass
class Dismiss:
    pass


@dataclass
class Clear:
    pass


Handler = Callable[[Any], Awaitable[None] | None]


class EventBus:
    def __init__(self) -> None:
        self._subs: dict[type, list[Handler]] = defaultdict(list)
        self._any: list[Handler] = []

    def subscribe(self, event_type: type | None, handler: Handler) -> None:
        """Subscribe to one event type, or to everything with None."""
        (self._any if event_type is None else self._subs[event_type]).append(handler)

    async def publish(self, event: Any) -> None:
        for h in (*self._subs.get(type(event), ()), *self._any):
            r = h(event)
            if inspect.isawaitable(r):
                await r

    def publish_nowait(self, event: Any) -> None:
        asyncio.get_running_loop().create_task(self.publish(event))
