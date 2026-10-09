"""Open-HUD wire protocol v1 — encoder/decoder.

Mirrors docs/PROTOCOL.md and firmware/src/protocol.h. Constant names are kept
identical to the C header so tests/test_protocol_sync.py can compare them.
"""
from __future__ import annotations

import struct
from dataclasses import dataclass

DEVICE_NAME = "OpenHUD"
SERVICE_UUID = "6f70656e-6875-6400-0001-000000000000"
RX_UUID = "6f70656e-6875-6400-0002-000000000000"
TX_UUID = "6f70656e-6875-6400-0003-000000000000"

PROTOCOL_VERSION = 1

MAX_FRAME = 64
HEADER_LEN = 3
MAX_PAYLOAD = 61
MAX_TEXT = 60
NOTIFY_SEP = 0x1F
MIN_MTU = MAX_FRAME + 3

# Host -> glasses
MSG_CLEAR = 0x01
MSG_TEXT = 0x02
MSG_NAV = 0x03
MSG_NOTIFY = 0x04
MSG_CONFIG = 0x05
MSG_PING = 0x06
MSG_DISMISS = 0x07

# Glasses -> host
MSG_STATUS = 0x81
MSG_ERROR = 0x82

# Slots
SLOT_STATUS_L = 0
SLOT_STATUS_R = 1
SLOT_MAIN = 2
SLOT_DETAIL = 3
SLOT_COUNT = 4

# Arrows
ARROW_NONE = 0
ARROW_STRAIGHT = 1
ARROW_SLIGHT_RIGHT = 2
ARROW_RIGHT = 3
ARROW_SHARP_RIGHT = 4
ARROW_UTURN = 5
ARROW_SHARP_LEFT = 6
ARROW_LEFT = 7
ARROW_SLIGHT_LEFT = 8
ARROW_ARRIVE = 9

DISTANCE_HIDDEN = 0xFFFF

# Apps
APP_GENERIC = 0
APP_CALL = 1
APP_MESSAGE = 2
APP_EMAIL = 3
APP_CALENDAR = 4
APP_AI = 5

# CONFIG flags
CFG_FLIP_H = 0x01
CFG_FLIP_V = 0x02
CFG_INVERT = 0x04

STATUS_PANEL_ON = 0x01
BATTERY_UNKNOWN = 0xFF

ERR_BAD_LENGTH = 1
ERR_UNKNOWN_TYPE = 2
ERR_BAD_SLOT = 3
ERR_QUEUE_FULL = 4

ERROR_NAMES = {
    ERR_BAD_LENGTH: "bad length",
    ERR_UNKNOWN_TYPE: "unknown type",
    ERR_BAD_SLOT: "bad slot",
    ERR_QUEUE_FULL: "queue full",
}


class ProtocolError(ValueError):
    pass


def _ascii(text: str, limit: int) -> bytes:
    """Encode already-cleaned text. Non-ASCII becomes '?' (preprocess first!)."""
    raw = text.encode("ascii", errors="replace")
    return raw[:limit]


@dataclass(frozen=True)
class Message:
    """One host->glasses update. `key` groups messages that overwrite each other
    (used by the sender to drop stale updates — "latest wins")."""

    type: int
    payload: bytes = b""

    def __post_init__(self) -> None:
        if len(self.payload) > MAX_PAYLOAD:
            raise ProtocolError(f"payload {len(self.payload)} B > {MAX_PAYLOAD} B")

    @property
    def key(self) -> tuple:
        if self.type == MSG_TEXT:
            return (MSG_TEXT, self.payload[0])
        return (self.type,)

    def encode(self, seq: int) -> bytes:
        return bytes((self.type, seq & 0xFF, len(self.payload))) + self.payload


# ----------------------------------------------------------------- builders

def clear() -> Message:
    return Message(MSG_CLEAR)


def text(slot: int, s: str) -> Message:
    if not 0 <= slot < SLOT_COUNT:
        raise ProtocolError(f"bad slot {slot}")
    return Message(MSG_TEXT, bytes((slot,)) + _ascii(s, MAX_TEXT))


def nav(arrow: int, distance_m: int | None, street: str = "") -> Message:
    d = DISTANCE_HIDDEN if distance_m is None else max(0, min(int(distance_m), 0xFFFE))
    return Message(MSG_NAV, struct.pack("<BH", arrow, d) + _ascii(street, MAX_PAYLOAD - 3))


def nav_end() -> Message:
    return nav(ARROW_NONE, None)


def notify(app: int, title: str, body: str = "", ttl_s: int = 6) -> Message:
    room = MAX_PAYLOAD - 2
    t = _ascii(title, room - 1 if body else room)  # leave space for the separator
    b = _ascii(body, room - len(t) - 1) if body else b""
    content = t + (bytes((NOTIFY_SEP,)) + b if b else b"")
    return Message(MSG_NOTIFY, bytes((app, max(0, min(ttl_s, 255)))) + content)


def config(
    *,
    flip_h: bool = False,
    flip_v: bool = False,
    invert: bool = False,
    offset_x: int = 0,
    offset_y: int = 0,
    contrast: int = 200,
    sleep_s: int = 60,
) -> Message:
    flags = (CFG_FLIP_H if flip_h else 0) | (CFG_FLIP_V if flip_v else 0) | (CFG_INVERT if invert else 0)
    ox = max(-32, min(32, offset_x))
    oy = max(-32, min(32, offset_y))
    return Message(
        MSG_CONFIG,
        struct.pack("<BbbBB", flags, ox, oy, max(0, min(contrast, 255)), max(0, min(sleep_s, 255))),
    )


def ping() -> Message:
    return Message(MSG_PING)


def dismiss() -> Message:
    return Message(MSG_DISMISS)


# ----------------------------------------------------------------- decoding

@dataclass(frozen=True)
class Frame:
    type: int
    seq: int
    payload: bytes


def decode(data: bytes) -> Frame:
    if len(data) < HEADER_LEN or len(data) > MAX_FRAME:
        raise ProtocolError(f"bad frame length {len(data)}")
    if HEADER_LEN + data[2] != len(data):
        raise ProtocolError("length byte does not match frame size")
    return Frame(data[0], data[1], bytes(data[HEADER_LEN:]))


@dataclass(frozen=True)
class Status:
    last_seq: int
    battery_pct: int | None
    panel_on: bool
    fw_version: int


def decode_status(payload: bytes) -> Status:
    if len(payload) < 4:
        raise ProtocolError("short STATUS")
    seq, batt, flags, fw = payload[:4]
    return Status(seq, None if batt == BATTERY_UNKNOWN else batt, bool(flags & STATUS_PANEL_ON), fw)
