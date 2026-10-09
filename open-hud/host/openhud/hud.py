"""Glue: EventBus -> Preprocessor -> HudLink, plus a few built-in sources."""
from __future__ import annotations

import asyncio
import time
from datetime import datetime

from . import events as ev
from .events import EventBus
from .link import HudLink
from .preprocess import Preprocessor
from .transport import Transport


class Hud:
    """One object an app needs: publish events, they show up on the glasses."""

    def __init__(self, transport: Transport) -> None:
        self.bus = EventBus()
        self.link = HudLink(transport)
        self.pre = Preprocessor()
        self.bus.subscribe(None, self._on_event)
        self._sources: list[asyncio.Task] = []
        self.last_event_ts: float | None = None

    def _on_event(self, e: object) -> None:
        self.last_event_ts = time.perf_counter()
        for m in self.pre.to_messages(e):
            self.link.submit(m)

    async def publish(self, e: object) -> None:
        await self.bus.publish(e)

    def add_source(self, coro) -> None:
        """Run a long-lived source coroutine (it receives the bus)."""
        self._sources.append(asyncio.create_task(coro(self.bus)))

    async def __aenter__(self) -> "Hud":
        await self.link.start()
        return self

    async def __aexit__(self, *exc) -> None:
        for t in self._sources:
            t.cancel()
        await self.link.flush(1.0)
        await self.link.stop()


# ------------------------------------------------------------------ sources

async def clock_source(bus: EventBus) -> None:
    """Puts the time in the top-left corner, updated on the minute."""
    while True:
        await bus.publish(ev.StatusText(left=datetime.now().strftime("%H:%M")))
        await asyncio.sleep(60 - datetime.now().second + 0.05)
