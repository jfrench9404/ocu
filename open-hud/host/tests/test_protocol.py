import re
from pathlib import Path

import pytest

from openhud import protocol as p

HEADER = Path(__file__).resolve().parents[2] / "firmware" / "src" / "protocol.h"


def test_c_and_python_constants_match():
    """firmware/src/protocol.h and protocol.py must agree on every constant."""
    src = HEADER.read_text()
    consts = re.findall(r"constexpr\s+uint(?:8|16)_t\s+(\w+)\s*=\s*(0x[0-9A-Fa-f]+|\d+)\s*;", src)
    assert len(consts) > 30
    for name, val in consts:
        if name == "FW_VERSION":
            continue
        assert getattr(p, name) == int(val, 0), name
    for name, attr in [("OPENHUD_SERVICE_UUID", "SERVICE_UUID"), ("OPENHUD_RX_UUID", "RX_UUID"),
                       ("OPENHUD_TX_UUID", "TX_UUID"), ("OPENHUD_DEVICE_NAME", "DEVICE_NAME")]:
        m = re.search(rf'#define\s+{name}\s+"([^"]+)"', src)
        assert m and m.group(1) == getattr(p, attr)


def test_text_roundtrip():
    raw = p.text(p.SLOT_MAIN, "Hello").encode(7)
    f = p.decode(raw)
    assert (f.type, f.seq, f.payload) == (p.MSG_TEXT, 7, bytes([p.SLOT_MAIN]) + b"Hello")


def test_frames_never_exceed_64_bytes():
    long = "x" * 500
    for m in [p.text(p.SLOT_DETAIL, long), p.nav(p.ARROW_LEFT, 123, long),
              p.notify(p.APP_MESSAGE, long, long), p.config(), p.clear(), p.ping()]:
        assert len(m.encode(255)) <= p.MAX_FRAME


def test_nav_encoding():
    f = p.decode(p.nav(p.ARROW_RIGHT, 1234, "Main St").encode(0))
    assert f.payload[:3] == bytes([p.ARROW_RIGHT, 1234 & 0xFF, 1234 >> 8])
    assert p.decode(p.nav(p.ARROW_LEFT, None).encode(0)).payload[1:3] == b"\xff\xff"


def test_notify_separator():
    f = p.decode(p.notify(p.APP_CALL, "Mom", "mobile", 0).encode(0))
    assert f.payload == bytes([p.APP_CALL, 0]) + b"Mom\x1fmobile"


def test_config_signed_offsets():
    f = p.decode(p.config(flip_h=True, offset_x=-5, offset_y=40).encode(0))
    assert f.payload[0] == p.CFG_FLIP_H
    assert f.payload[1] == 256 - 5
    assert f.payload[2] == 32  # clamped


def test_bad_slot_rejected():
    with pytest.raises(p.ProtocolError):
        p.text(9, "x")


def test_decode_rejects_bad_length():
    with pytest.raises(p.ProtocolError):
        p.decode(bytes([p.MSG_TEXT, 0, 10, 1]))


def test_status_decode():
    s = p.decode_status(bytes([42, 0xFF, 1, 1]))
    assert s.last_seq == 42 and s.battery_pct is None and s.panel_on
