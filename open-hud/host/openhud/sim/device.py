"""Python port of firmware/src/hud_state.cpp, so the protocol and layouts can be
exercised with no hardware. Keep behaviour in sync with the C++ version."""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Callable

from .. import protocol as p


def _clean(b: bytes) -> str:
    return "".join(chr(c) if 0x20 <= c <= 0x7E else "?" for c in b[: p.MAX_TEXT])


@dataclass
class HudConfig:
    flags: int = 0
    offset_x: int = 0
    offset_y: int = 0
    contrast: int = 200
    sleep_s: int = 60


@dataclass
class HudState:
    slots: list[str] = field(default_factory=lambda: [""] * p.SLOT_COUNT)
    nav_active: bool = False
    nav_arrow: int = 0
    nav_distance_m: int = p.DISTANCE_HIDDEN
    nav_text: str = ""
    notif_active: bool = False
    notif_app: int = 0
    notif_expires: float | None = None
    notif_title: str = ""
    notif_body: str = ""
    cfg: HudConfig = field(default_factory=HudConfig)
    last_seq: int = 0


class SimDevice:
    def __init__(self, clock: Callable[[], float] = time.monotonic) -> None:
        self.state = HudState()
        self.state.slots[p.SLOT_MAIN] = "Open-HUD"
        self.connected = False
        self.clock = clock
        self.on_notify: Callable[[bytes], None] | None = None
        self.on_change: Callable[[], None] | None = None
        self.frames_received = 0
        self.errors: list[int] = []

    # --------------------------------------------------------------- I/O

    def set_connected(self, c: bool) -> None:
        self.connected = c
        if c:
            self._send_status()
        self._changed()

    def receive(self, data: bytes) -> None:
        self.frames_received += 1
        err = self.apply(data)
        if err:
            self.errors.append(err)
            self._notify(bytes((p.MSG_ERROR, 0, 2, data[1] if len(data) > 1 else 0, err)))
        self._changed()

    def tick(self) -> None:
        s = self.state
        if s.notif_active and s.notif_expires is not None and self.clock() >= s.notif_expires:
            s.notif_active = False
            self._changed()

    def _send_status(self) -> None:
        self._notify(bytes((p.MSG_STATUS, 0, 4, self.state.last_seq, p.BATTERY_UNKNOWN,
                            p.STATUS_PANEL_ON, 1)))

    def _notify(self, data: bytes) -> None:
        if self.connected and self.on_notify:
            self.on_notify(data)

    def _changed(self) -> None:
        if self.on_change:
            self.on_change()

    # --------------------------------------------------------------- state machine

    def apply(self, f: bytes) -> int:
        s = self.state
        if len(f) < p.HEADER_LEN or len(f) > p.MAX_FRAME:
            return p.ERR_BAD_LENGTH
        typ, seq, plen = f[0], f[1], f[2]
        if p.HEADER_LEN + plen != len(f):
            return p.ERR_BAD_LENGTH
        pl = f[p.HEADER_LEN:]
        s.last_seq = seq

        if typ == p.MSG_CLEAR:
            s.slots = [""] * p.SLOT_COUNT
            s.nav_active = False
            s.nav_text = ""
            s.notif_active = False
        elif typ == p.MSG_TEXT:
            if plen < 1:
                return p.ERR_BAD_LENGTH
            if pl[0] >= p.SLOT_COUNT:
                return p.ERR_BAD_SLOT
            s.slots[pl[0]] = _clean(pl[1:])
        elif typ == p.MSG_NAV:
            if plen < 3:
                return p.ERR_BAD_LENGTH
            s.nav_arrow = pl[0]
            s.nav_active = pl[0] != p.ARROW_NONE
            s.nav_distance_m = pl[1] | (pl[2] << 8)
            s.nav_text = _clean(pl[3:])
        elif typ == p.MSG_NOTIFY:
            if plen < 2:
                return p.ERR_BAD_LENGTH
            s.notif_app, ttl = pl[0], pl[1]
            title, _, body = pl[2:].partition(bytes((p.NOTIFY_SEP,)))
            s.notif_title, s.notif_body = _clean(title), _clean(body)
            s.notif_expires = self.clock() + ttl if ttl else None
            s.notif_active = True
        elif typ == p.MSG_CONFIG:
            if plen != 5:
                return p.ERR_BAD_LENGTH
            ox = pl[1] - 256 if pl[1] > 127 else pl[1]
            oy = pl[2] - 256 if pl[2] > 127 else pl[2]
            s.cfg = HudConfig(pl[0], max(-32, min(32, ox)), max(-32, min(32, oy)), pl[3], pl[4])
        elif typ == p.MSG_PING:
            self._send_status()
        elif typ == p.MSG_DISMISS:
            s.notif_active = False
        else:
            return p.ERR_UNKNOWN_TYPE
        return 0
