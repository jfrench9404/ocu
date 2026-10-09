"""HudLink: the reliable, low-latency sender between the event pipeline and a
transport.

- Latest wins: if several updates for the same thing (e.g. MAIN text) queue
  up while the radio is busy, only the newest is sent.
- Auto-reconnect with short backoff; on reconnect the current screen state is
  re-sent, so a glasses reboot or range drop heals itself.
- Measures round-trip latency with PING/STATUS.
"""
from __future__ import annotations

import asyncio
import logging
import time
from collections import OrderedDict
from typing import Callable

from . import protocol as p
from .transport import Transport

log = logging.getLogger("openhud.link")


class HudLink:
    def __init__(self, transport: Transport, *, max_backoff_s: float = 2.0) -> None:
        self.t = transport
        self.t.on_receive = self._on_receive
        self.t.on_disconnect = self._on_disconnect
        self.max_backoff_s = max_backoff_s

        self._pending: OrderedDict[tuple, p.Message] = OrderedDict()
        self._state: OrderedDict[tuple, p.Message] = OrderedDict()  # replayed on reconnect
        self._wake = asyncio.Event()
        self._seq = 0
        self._ping_waiters: dict[int, tuple[float, asyncio.Future]] = {}
        self._task: asyncio.Task | None = None
        self._running = False

        self.status: p.Status | None = None
        self.on_status: Callable[[p.Status], None] | None = None
        self.on_error: Callable[[int, int], None] | None = None
        self.connected_event = asyncio.Event()

    # ---------------------------------------------------------- public API

    def submit(self, msg: p.Message) -> None:
        """Queue a message. Replaces any not-yet-sent message with the same key."""
        self._pending.pop(msg.key, None)
        self._pending[msg.key] = msg
        self._remember(msg)
        self._wake.set()

    async def start(self) -> None:
        self._running = True
        self._task = asyncio.create_task(self._run(), name="hudlink")

    async def stop(self) -> None:
        self._running = False
        self._wake.set()
        if self._task:
            await self._task
        await self.t.close()

    async def flush(self, timeout: float = 5.0) -> None:
        """Wait until everything queued has been handed to the transport."""
        end = time.monotonic() + timeout
        while self._pending and time.monotonic() < end:
            await asyncio.sleep(0.01)

    async def ping(self, timeout: float = 2.0) -> float:
        """Round-trip time in milliseconds (host -> glasses -> host)."""
        fut: asyncio.Future = asyncio.get_running_loop().create_future()
        seq = self._next_seq()
        # Register before sending: the reply can arrive before send() returns.
        self._ping_waiters[seq] = (time.perf_counter(), fut)
        try:
            await self.t.send(p.ping().encode(seq))
            return await asyncio.wait_for(fut, timeout)
        finally:
            self._ping_waiters.pop(seq, None)

    # ---------------------------------------------------------- internals

    def _remember(self, msg: p.Message) -> None:
        """Keep the latest 'screen state' so it can be replayed after a reconnect."""
        if msg.type == p.MSG_CLEAR:
            for k in [k for k in self._state if k[0] in (p.MSG_TEXT, p.MSG_NAV, p.MSG_NOTIFY)]:
                del self._state[k]
        elif msg.type in (p.MSG_TEXT, p.MSG_NAV, p.MSG_CONFIG):
            self._state.pop(msg.key, None)
            self._state[msg.key] = msg
        elif msg.type == p.MSG_DISMISS:
            self._state.pop((p.MSG_NOTIFY,), None)

    def _next_seq(self) -> int:
        self._seq = (self._seq + 1) & 0xFF
        return self._seq

    async def _send_now(self, msg: p.Message) -> int:
        seq = self._next_seq()
        await self.t.send(msg.encode(seq))
        return seq

    def _on_receive(self, data: bytes) -> None:
        try:
            f = p.decode(data)
        except p.ProtocolError as e:
            log.warning("bad frame from glasses: %s", e)
            return
        if f.type == p.MSG_STATUS:
            self.status = p.decode_status(f.payload)
            waiter = self._ping_waiters.get(self.status.last_seq)
            if waiter and not waiter[1].done():
                waiter[1].set_result((time.perf_counter() - waiter[0]) * 1000.0)
            if self.on_status:
                self.on_status(self.status)
        elif f.type == p.MSG_ERROR and len(f.payload) >= 2:
            seq, code = f.payload[0], f.payload[1]
            log.warning("glasses rejected seq %d: %s", seq, p.ERROR_NAMES.get(code, code))
            if self.on_error:
                self.on_error(seq, code)

    def _on_disconnect(self) -> None:
        self.connected_event.clear()
        self._wake.set()

    async def _ensure_connected(self) -> None:
        backoff = 0.1
        while self._running and not self.t.connected:
            try:
                t0 = time.perf_counter()
                await self.t.connect()
                log.info("link up in %.0f ms", (time.perf_counter() - t0) * 1000)
                # Replay the current screen, config first, before newer updates.
                replay = OrderedDict(self._state)
                if (p.MSG_CONFIG,) in replay:
                    replay.move_to_end((p.MSG_CONFIG,), last=False)
                for k, m in reversed(replay.items()):
                    if k not in self._pending:
                        self._pending[k] = m
                        self._pending.move_to_end(k, last=False)
                self.connected_event.set()
            except Exception as e:  # noqa: BLE001 - any connect failure -> retry
                log.info("connect failed (%s); retry in %.1fs", e, backoff)
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, self.max_backoff_s)

    async def _run(self) -> None:
        while self._running:
            await self._ensure_connected()
            if not self._pending:
                self._wake.clear()
                await self._wake.wait()
                continue
            key, msg = next(iter(self._pending.items()))
            try:
                await self._send_now(msg)
                # Only drop it if a newer one didn't arrive while we were sending.
                if self._pending.get(key) is msg:
                    del self._pending[key]
            except ConnectionError:
                self.connected_event.clear()
            except Exception as e:  # noqa: BLE001 - e.g. a GATT write error
                log.warning("send failed: %s", e)
                await asyncio.sleep(0.1)
