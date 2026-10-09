"""Pillow port of firmware/src/renderer.cpp — draws a 128x64 1-bit frame.

Fonts are approximations of the U8g2 fonts (system TrueType fonts, falling
back to Pillow's built-in), so expect a pixel or two of difference from the
real panel. Geometry (regions, arrows, offsets, flips) matches the firmware.
"""
from __future__ import annotations

import math
from functools import lru_cache

from PIL import Image, ImageDraw, ImageFont, ImageOps

from .. import protocol as p
from .device import HudState

W, H = 128, 64
STATUS_BASE = 7
MAIN_TEXT_BASE = 38
DETAIL_BASE = 63
ARROW_CX, ARROW_CY = 20, 32
NAV_TEXT_X, NAV_DIST_BASE, NAV_STREET_BASE = 44, 32, 47
NOTIF_ICON_X, NOTIF_ICON_Y, NOTIF_ICON_S = 0, 13, 15
NOTIF_TITLE_X, NOTIF_TITLE_BASE = 19, 25
NOTIF_BODY_BASE1, NOTIF_BODY_BASE2 = 39, 50
SMALL_CHARS_PER_LINE = 21

_MONO = ["DejaVuSansMono.ttf", "consola.ttf", "Menlo.ttc", "LiberationMono-Regular.ttf"]
_BOLD = ["DejaVuSans-Bold.ttf", "arialbd.ttf", "Arial Bold.ttf", "LiberationSans-Bold.ttf",
         "Helvetica.ttc"]


@lru_cache(maxsize=None)
def _font(kind: str, size: int):
    for name in (_MONO if kind == "mono" else _BOLD):
        try:
            return ImageFont.truetype(name, size)
        except OSError:
            continue
    return ImageFont.load_default(size=size)


def FONT_TINY():  return _font("mono", 8)    # ~ u8g2_font_5x7_tr
def FONT_SMALL(): return _font("mono", 10)   # ~ u8g2_font_6x10_tr
def FONT_MED():   return _font("bold", 11)   # ~ u8g2_font_helvB10_tr
def FONT_BIG():   return _font("bold", 15)   # ~ u8g2_font_helvB14_tr


def format_distance(m: int) -> str:
    if m == p.DISTANCE_HIDDEN:
        return ""
    if m < 1000:
        return f"{m} m"
    if m < 10000:
        tenths = (m + 50) // 100
        return f"{tenths // 10}.{tenths % 10} km"
    return f"{(m + 500) // 1000} km"


class _Canvas:
    def __init__(self, ox: int, oy: int) -> None:
        self.img = Image.new("1", (W, H), 0)
        self.d = ImageDraw.Draw(self.img)
        self.d.fontmode = "1"
        self.ox, self.oy = ox, oy

    def width(self, text: str, font) -> int:
        return int(self.d.textlength(text, font=font))

    def text(self, x: int, y: int, s: str, font) -> None:
        self.d.text((x + self.ox, y + self.oy), s, fill=1, font=font, anchor="ls")

    def fit(self, x: int, y: int, s: str, font, max_w: int) -> None:
        if self.width(s, font) > max_w:
            while s and self.width(s + "..", font) > max_w:
                s = s[:-1]
            s += ".."
        self.text(x, y, s, font)

    def poly(self, pts) -> None:
        self.d.polygon([(round(x + self.ox), round(y + self.oy)) for x, y in pts], fill=1)

    def disc(self, cx, cy, r, fill=True) -> None:
        box = [cx - r + self.ox, cy - r + self.oy, cx + r + self.ox, cy + r + self.oy]
        if fill:
            self.d.ellipse(box, fill=1)
        else:
            self.d.ellipse(box, outline=1)


def _thick_line(c: _Canvas, x0, y0, x1, y1, w) -> None:
    dx, dy = x1 - x0, y1 - y0
    ln = math.hypot(dx, dy)
    if ln < 0.01:
        return
    nx, ny = -dy / ln * w, dx / ln * w
    c.poly([(x0 + nx, y0 + ny), (x1 + nx, y1 + ny), (x1 - nx, y1 - ny), (x0 - nx, y0 - ny)])


_ANGLES = {
    p.ARROW_SLIGHT_RIGHT: 45, p.ARROW_RIGHT: 90, p.ARROW_SHARP_RIGHT: 135,
    p.ARROW_SHARP_LEFT: -135, p.ARROW_LEFT: -90, p.ARROW_SLIGHT_LEFT: -45,
}


def _arrow(c: _Canvas, arrow: int, cx: int, cy: int) -> None:
    if arrow == p.ARROW_ARRIVE:
        c.disc(cx, cy, 6)
        c.disc(cx, cy, 12, fill=False)
        c.disc(cx, cy, 13, fill=False)
        return
    if arrow == p.ARROW_UTURN:
        r, top = 7, cy - 4
        c.poly([(cx + r - 2, top), (cx + r + 2, top), (cx + r + 2, top + 21), (cx + r - 2, top + 21)])
        c.d.arc([cx - r - 2 + c.ox, top - r - 2 + c.oy, cx + r + 2 + c.ox, top + r + 2 + c.oy],
                180, 360, fill=1, width=5)
        c.poly([(cx - r - 2, top), (cx - r + 2, top), (cx - r + 2, top + 8), (cx - r - 2, top + 8)])
        c.poly([(cx - r - 8, top + 9), (cx - r + 8, top + 9), (cx - r, top + 18)])
        return
    a = math.radians(_ANGLES.get(arrow, 0))
    dx, dy = math.sin(a), -math.cos(a)
    sharp = max(0.0, dy)  # same rule as firmware: keep the head clear of the stem
    sx = cx - (6 + 8.5 * sharp) * dx
    jx, jy = sx, cy + 4 - 17 * sharp
    seg, head = 12 + 3 * sharp, 8 - 3 * sharp
    _thick_line(c, sx, cy + 18, jx, jy, 2.5)
    c.disc(round(jx), round(jy), 2)
    ex, ey = jx + dx * seg, jy + dy * seg
    _thick_line(c, jx, jy, ex, ey, 2.5)
    tx, ty = ex + dx * 9, ey + dy * 9
    px, py = -dy * head, dx * head
    c.poly([(tx, ty), (ex + px, ey + py), (ex - px, ey - py)])


_GLYPH = {p.APP_CALL: "C", p.APP_MESSAGE: "M", p.APP_EMAIL: "@", p.APP_CALENDAR: "#", p.APP_AI: "*"}


def _body(c: _Canvas, body: str) -> None:
    n = SMALL_CHARS_PER_LINE
    cut = len(body) if len(body) <= n else n
    if len(body) > n:
        for i in range(n, n // 2, -1):
            if body[i] == " ":
                cut = i
                break
    c.text(0, NOTIF_BODY_BASE1, body[:cut], FONT_SMALL())
    rest = body[cut:].lstrip(" ")
    if rest:
        c.fit(0, NOTIF_BODY_BASE2, rest, FONT_SMALL(), W)


def render(s: HudState, connected: bool = True) -> Image.Image:
    """Return the 128x64 1-bit frame exactly as the panel would show it."""
    c = _Canvas(s.cfg.offset_x, s.cfg.offset_y)

    # status bar
    c.text(0, STATUS_BASE, s.slots[p.SLOT_STATUS_L], FONT_TINY())
    right = s.slots[p.SLOT_STATUS_R] if connected else "no link"
    c.text(W - 1 - c.width(right, FONT_TINY()), STATUS_BASE, right, FONT_TINY())

    # main area
    if s.notif_active:
        c.d.rounded_rectangle([NOTIF_ICON_X + c.ox, NOTIF_ICON_Y + c.oy,
                               NOTIF_ICON_X + NOTIF_ICON_S - 1 + c.ox,
                               NOTIF_ICON_Y + NOTIF_ICON_S - 1 + c.oy], radius=3, outline=1)
        c.text(NOTIF_ICON_X + 5, NOTIF_ICON_Y + 11, _GLYPH.get(s.notif_app, "!"), FONT_SMALL())
        c.fit(NOTIF_TITLE_X, NOTIF_TITLE_BASE, s.notif_title, FONT_MED(), W - NOTIF_TITLE_X)
        _body(c, s.notif_body)
    elif s.nav_active:
        _arrow(c, s.nav_arrow, ARROW_CX, ARROW_CY)
        c.text(NAV_TEXT_X, NAV_DIST_BASE, format_distance(s.nav_distance_m), FONT_BIG())
        c.fit(NAV_TEXT_X, NAV_STREET_BASE, s.nav_text, FONT_SMALL(), W - NAV_TEXT_X)
    elif s.slots[p.SLOT_MAIN]:
        t = s.slots[p.SLOT_MAIN]
        w = c.width(t, FONT_BIG())
        if w > W:
            c.fit(0, MAIN_TEXT_BASE, t, FONT_BIG(), W)
        else:
            c.text((W - w) // 2, MAIN_TEXT_BASE, t, FONT_BIG())

    # detail line
    c.fit(0, DETAIL_BASE, s.slots[p.SLOT_DETAIL], FONT_SMALL(), W)

    img = c.img
    if s.cfg.flags & p.CFG_FLIP_H:
        img = ImageOps.mirror(img)
    if s.cfg.flags & p.CFG_FLIP_V:
        img = ImageOps.flip(img)
    if s.cfg.flags & p.CFG_INVERT:
        img = img.point(lambda v: 255 - v)
    return img


def preview(frame: Image.Image, scale: int = 5, color=(140, 230, 255)) -> Image.Image:
    """Upscale a 1-bit frame with a visible pixel grid, like a real micro-OLED."""
    out = Image.new("RGB", (W * scale, H * scale), (0, 0, 0))
    d = ImageDraw.Draw(out)
    px = frame.load()
    gap = 1 if scale >= 4 else 0
    for y in range(H):
        for x in range(W):
            if px[x, y]:
                d.rectangle([x * scale, y * scale, (x + 1) * scale - 1 - gap,
                             (y + 1) * scale - 1 - gap], fill=color)
    return out
