"""Turn rich phone data into tiny, glanceable HUD primitives.

Everything heavy happens here, on the phone/laptop, so the microcontroller only
copies bytes. Rules: ASCII only, short, single-purpose, readable in < 500 ms.
"""
from __future__ import annotations

import re
import time
import unicodedata

from . import events as ev
from . import protocol as p

# Visible character budgets per slot (see docs/PROTOCOL.md).
SLOT_CHARS = {
    p.SLOT_STATUS_L: 12,
    p.SLOT_STATUS_R: 8,
    p.SLOT_MAIN: 12,
    p.SLOT_DETAIL: 21,
}
NOTIF_TITLE_CHARS = 16
NOTIF_BODY_CHARS = 42      # two lines of 21
NAV_STREET_CHARS = 14

_REPLACEMENTS = {
    "‘": "'", "’": "'", "“": '"', "”": '"',
    "–": "-", "—": "-", "…": "...", " ": " ",
    "°": "deg", "€": "EUR", "£": "GBP", "ß": "ss",
    "æ": "ae", "ø": "o", "ł": "l",
}

_EMOJI_RE = re.compile("[\U0001F000-\U0001FAFF☀-➿️]")


def fold(s: str) -> str:
    """Unicode -> printable ASCII. Accents dropped, emoji removed, whitespace collapsed."""
    s = _EMOJI_RE.sub("", s)
    s = "".join(_REPLACEMENTS.get(ch, ch) for ch in s)
    s = unicodedata.normalize("NFKD", s)
    s = "".join(ch for ch in s if 0x20 <= ord(ch) <= 0x7E or ch.isspace())
    return " ".join(s.split())


def fit(s: str, n: int) -> str:
    """Truncate to n characters, ending with '..' when cut (prefer word breaks)."""
    s = fold(s)
    if len(s) <= n:
        return s
    cut = s[: n - 2]
    space = cut.rfind(" ")
    if space >= n // 2:
        cut = cut[:space]
    return cut.rstrip(" ,.;:-") + ".."


# ------------------------------------------------------------------ nav

_MANEUVERS = {
    "straight": p.ARROW_STRAIGHT, "continue": p.ARROW_STRAIGHT, "depart": p.ARROW_STRAIGHT,
    "slight right": p.ARROW_SLIGHT_RIGHT, "right": p.ARROW_RIGHT, "sharp right": p.ARROW_SHARP_RIGHT,
    "slight left": p.ARROW_SLIGHT_LEFT, "left": p.ARROW_LEFT, "sharp left": p.ARROW_SHARP_LEFT,
    "uturn": p.ARROW_UTURN, "u-turn": p.ARROW_UTURN, "arrive": p.ARROW_ARRIVE,
}

_STREET_ABBR = [
    (r"\bStreet\b", "St"), (r"\bAvenue\b", "Ave"), (r"\bRoad\b", "Rd"),
    (r"\bBoulevard\b", "Blvd"), (r"\bDrive\b", "Dr"), (r"\bLane\b", "Ln"),
    (r"\bHighway\b", "Hwy"), (r"\bParkway\b", "Pkwy"), (r"\bPlace\b", "Pl"),
    (r"\bCourt\b", "Ct"), (r"\bNorth\b", "N"), (r"\bSouth\b", "S"),
    (r"\bEast\b", "E"), (r"\bWest\b", "W"),
]


def maneuver_to_arrow(maneuver: str) -> int:
    m = maneuver.lower().replace("_", " ").strip()
    if m in _MANEUVERS:
        return _MANEUVERS[m]
    for word, arrow in sorted(_MANEUVERS.items(), key=lambda kv: -len(kv[0])):
        if word in m:
            return arrow
    return p.ARROW_STRAIGHT


def shorten_street(street: str) -> str:
    s = fold(street)
    for pat, rep in _STREET_ABBR:
        s = re.sub(pat, rep, s, flags=re.IGNORECASE)
    return fit(s, NAV_STREET_CHARS)


def round_distance(m: float | None) -> int | None:
    """Round like a human would read it: 5 m steps close, 10 m mid, 100 m far."""
    if m is None:
        return None
    m = max(0.0, m)
    if m < 100:
        step = 5
    elif m < 1000:
        step = 10
    else:
        step = 100
    return int(round(m / step) * step)


# ------------------------------------------------------------------ notifications

_APPS = {
    "call": p.APP_CALL, "phone": p.APP_CALL,
    "message": p.APP_MESSAGE, "sms": p.APP_MESSAGE, "chat": p.APP_MESSAGE,
    "email": p.APP_EMAIL, "mail": p.APP_EMAIL,
    "calendar": p.APP_CALENDAR, "event": p.APP_CALENDAR,
    "ai": p.APP_AI, "llm": p.APP_AI,
}


def app_code(app: str) -> int:
    return _APPS.get(app.lower().strip(), p.APP_GENERIC)


# ------------------------------------------------------------------ LLM streaming

class LlmTicker:
    """Shows a streaming AI answer as a rolling 2-line notification.

    Rate-limited so a fast token stream doesn't flood BLE: at most one update
    per `min_interval_s`, always flushing on done.
    """

    def __init__(self, min_interval_s: float = 0.15, ttl_after_done_s: int = 8) -> None:
        self.buf = ""
        self.min_interval_s = min_interval_s
        self.ttl_after_done_s = ttl_after_done_s
        self._last = 0.0

    def feed(self, chunk: ev.LlmChunk, now: float | None = None) -> p.Message | None:
        now = time.monotonic() if now is None else now
        self.buf += chunk.text
        if not chunk.done and now - self._last < self.min_interval_s:
            return None
        self._last = now
        body = fold(self.buf)
        if len(body) > NOTIF_BODY_CHARS:
            tail = body[-(NOTIF_BODY_CHARS - 2):]
            sp = tail.find(" ")
            if 0 <= sp < 10:
                tail = tail[sp + 1:]
            body = ".." + tail
        ttl = self.ttl_after_done_s if chunk.done else 0
        if chunk.done:
            self.buf = ""
        return p.notify(p.APP_AI, fit(chunk.title, NOTIF_TITLE_CHARS), body, ttl)


# ------------------------------------------------------------------ dispatcher

class Preprocessor:
    """Maps events -> protocol messages."""

    def __init__(self) -> None:
        self.llm = LlmTicker()

    def to_messages(self, e: object) -> list[p.Message]:
        if isinstance(e, ev.Notification):
            return [p.notify(app_code(e.app), fit(e.title, NOTIF_TITLE_CHARS),
                             fit(e.body, NOTIF_BODY_CHARS), e.ttl_s)]
        if isinstance(e, ev.NavUpdate):
            return [p.nav(maneuver_to_arrow(e.maneuver), round_distance(e.distance_m),
                          shorten_street(e.street))]
        if isinstance(e, ev.NavEnd):
            return [p.nav_end()]
        if isinstance(e, ev.StatusText):
            out = []
            if e.left is not None:
                out.append(p.text(p.SLOT_STATUS_L, fit(e.left, SLOT_CHARS[p.SLOT_STATUS_L])))
            if e.right is not None:
                out.append(p.text(p.SLOT_STATUS_R, fit(e.right, SLOT_CHARS[p.SLOT_STATUS_R])))
            return out
        if isinstance(e, ev.MainText):
            return [p.text(p.SLOT_MAIN, fit(e.text, SLOT_CHARS[p.SLOT_MAIN]))]
        if isinstance(e, ev.DetailText):
            return [p.text(p.SLOT_DETAIL, fit(e.text, SLOT_CHARS[p.SLOT_DETAIL]))]
        if isinstance(e, ev.LlmChunk):
            m = self.llm.feed(e)
            return [m] if m else []
        if isinstance(e, ev.Dismiss):
            return [p.dismiss()]
        if isinstance(e, ev.Clear):
            return [p.clear()]
        return []
