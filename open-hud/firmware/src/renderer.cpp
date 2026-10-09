#include "renderer.h"

#include <Arduino.h>
#include <U8g2lib.h>
#include <Wire.h>
#include <math.h>
#include <stdio.h>
#include <string.h>

#include "config.h"

using namespace proto;
using namespace layout;

// Full-buffer mode: 128*64/8 = 1024 bytes, allocated statically by U8g2.
static U8G2_SSD1306_128X64_NONAME_F_HW_I2C d(U8G2_R0, U8X8_PIN_NONE, PIN_I2C_SCL,
                                             PIN_I2C_SDA);
static bool g_panel_on = true;
static int g_ox = 0, g_oy = 0;

// Fonts (all from U8g2's built-in set, stored in flash).
#define FONT_TINY  u8g2_font_5x7_tr
#define FONT_SMALL u8g2_font_6x10_tr
#define FONT_MED   u8g2_font_helvB10_tr
#define FONT_BIG   u8g2_font_helvB14_tr

// ---------------------------------------------------------------- helpers

void format_distance(uint16_t m, char* out, size_t n) {
  if (m == DISTANCE_HIDDEN) {
    out[0] = '\0';
  } else if (m < 1000) {
    snprintf(out, n, "%u m", (unsigned)m);
  } else if (m < 10000) {
    unsigned tenths = (m + 50) / 100;  // round to 0.1 km
    snprintf(out, n, "%u.%u km", tenths / 10, tenths % 10);
  } else {
    snprintf(out, n, "%u km", (unsigned)((m + 500) / 1000));
  }
}

// Draw text, cutting it with ".." if it would exceed max_w pixels.
static void draw_fit(int x, int y, const char* text, int max_w) {
  char buf[MAX_TEXT + 3];
  strncpy(buf, text, MAX_TEXT);
  buf[MAX_TEXT] = '\0';
  if (d.getStrWidth(buf) > max_w) {
    size_t n = strlen(buf);
    while (n > 0) {
      n--;
      buf[n] = '\0';
      char tmp[MAX_TEXT + 3];
      snprintf(tmp, sizeof(tmp), "%s..", buf);
      if (d.getStrWidth(tmp) <= max_w) {
        strcpy(buf, tmp);
        break;
      }
    }
  }
  d.drawStr(x, y, buf);
}

static void thick_line(float x0, float y0, float x1, float y1, float w) {
  float dx = x1 - x0, dy = y1 - y0;
  float len = sqrtf(dx * dx + dy * dy);
  if (len < 0.01f) return;
  float nx = -dy / len * w, ny = dx / len * w;
  d.drawTriangle(lroundf(x0 + nx), lroundf(y0 + ny), lroundf(x1 + nx), lroundf(y1 + ny),
                 lroundf(x1 - nx), lroundf(y1 - ny));
  d.drawTriangle(lroundf(x0 + nx), lroundf(y0 + ny), lroundf(x1 - nx), lroundf(y1 - ny),
                 lroundf(x0 - nx), lroundf(y0 - ny));
}

static int arrow_angle_deg(uint8_t a) {
  switch (a) {
    case ARROW_SLIGHT_RIGHT: return 45;
    case ARROW_RIGHT: return 90;
    case ARROW_SHARP_RIGHT: return 135;
    case ARROW_SHARP_LEFT: return -135;
    case ARROW_LEFT: return -90;
    case ARROW_SLIGHT_LEFT: return -45;
    default: return 0;
  }
}

// Turn arrow: a vertical stem (the road you're on) that bends toward the turn.
static void draw_arrow(uint8_t arrow, int cx, int cy) {
  if (arrow == ARROW_ARRIVE) {
    d.drawDisc(cx, cy, 6);
    d.drawCircle(cx, cy, 12);
    d.drawCircle(cx, cy, 13);
    return;
  }
  if (arrow == ARROW_UTURN) {
    const int r = 7, top = cy - 4;
    d.drawBox(cx + r - 2, top, 5, 22);                       // right leg (up)
    for (int rr = r - 2; rr <= r + 2; rr++)
      d.drawCircle(cx, top, rr, U8G2_DRAW_UPPER_LEFT | U8G2_DRAW_UPPER_RIGHT);
    d.drawBox(cx - r - 2, top, 5, 9);                        // left leg (down)
    d.drawTriangle(cx - r - 8, top + 9, cx - r + 8, top + 9, cx - r, top + 18);
    return;
  }
  const float a = arrow_angle_deg(arrow) * (float)M_PI / 180.0f;
  const float dx = sinf(a), dy = -cosf(a);
  // Sharp turns point backwards; raise the joint, push the stem further
  // aside and slim the head so it doesn't collide with the stem.
  const float sharp = dy > 0 ? dy : 0.0f;
  const float sx = cx - (6.0f + 8.5f * sharp) * dx;    // shift stem away from turn
  const float jx = sx, jy = cy + 4.0f - 17.0f * sharp;  // joint
  const float seg = 12.0f + 3.0f * sharp, head = 8.0f - 3.0f * sharp;
  thick_line(sx, cy + 18.0f, jx, jy, 2.5f);
  d.drawDisc(lroundf(jx), lroundf(jy), 2);
  const float ex = jx + dx * seg, ey = jy + dy * seg;
  thick_line(jx, jy, ex, ey, 2.5f);
  const float tx = ex + dx * 9.0f, ty = ey + dy * 9.0f;
  const float px = -dy * head, py = dx * head;
  d.drawTriangle(lroundf(tx), lroundf(ty), lroundf(ex + px), lroundf(ey + py),
                 lroundf(ex - px), lroundf(ey - py));
}

static char app_glyph(uint8_t app) {
  switch (app) {
    case APP_CALL: return 'C';
    case APP_MESSAGE: return 'M';
    case APP_EMAIL: return '@';
    case APP_CALENDAR: return '#';
    case APP_AI: return '*';
    default: return '!';
  }
}

// Split body into <= 2 lines of SMALL_CHARS_PER_LINE, breaking at spaces.
static void draw_body(int x, const char* body) {
  const size_t W1 = SMALL_CHARS_PER_LINE;
  char line[SMALL_CHARS_PER_LINE + 1];
  size_t len = strlen(body);
  size_t cut = len <= W1 ? len : W1;
  if (len > W1) {
    for (size_t i = W1; i > W1 / 2; i--) {
      if (body[i] == ' ') { cut = i; break; }
    }
  }
  memcpy(line, body, cut);
  line[cut] = '\0';
  d.drawStr(x, NOTIF_BODY_BASE1 + g_oy, line);
  const char* rest = body + cut;
  while (*rest == ' ') rest++;
  if (*rest) draw_fit(x, NOTIF_BODY_BASE2 + g_oy, rest, W - x);
}

// ---------------------------------------------------------------- regions

static void draw_status(const HudState& s, bool connected) {
  d.setFont(FONT_TINY);
  d.drawStr(g_ox, STATUS_BASE + g_oy, s.slots[SLOT_STATUS_L]);
  const char* right = connected ? s.slots[SLOT_STATUS_R] : "no link";
  int w = d.getStrWidth(right);
  d.drawStr(W - 1 - w + g_ox, STATUS_BASE + g_oy, right);
}

static void draw_main(const HudState& s) {
  if (s.notif_active) {
    const int ix = NOTIF_ICON_X + g_ox, iy = NOTIF_ICON_Y + g_oy;
    d.drawRFrame(ix, iy, NOTIF_ICON_S, NOTIF_ICON_S, 3);
    d.setFont(FONT_SMALL);
    char g[2] = {app_glyph(s.notif_app), 0};
    d.drawStr(ix + 5, iy + 11, g);
    d.setFont(FONT_MED);
    draw_fit(NOTIF_TITLE_X + g_ox, NOTIF_TITLE_BASE + g_oy, s.notif_title, W - NOTIF_TITLE_X);
    d.setFont(FONT_SMALL);
    draw_body(g_ox, s.notif_body);
  } else if (s.nav_active) {
    draw_arrow(s.nav_arrow, ARROW_CX + g_ox, ARROW_CY + g_oy);
    char dist[16];
    format_distance(s.nav_distance_m, dist, sizeof(dist));
    d.setFont(FONT_BIG);
    d.drawStr(NAV_TEXT_X + g_ox, NAV_DIST_BASE + g_oy, dist);
    d.setFont(FONT_SMALL);
    draw_fit(NAV_TEXT_X + g_ox, NAV_STREET_BASE + g_oy, s.nav_text, W - NAV_TEXT_X);
  } else if (s.slots[SLOT_MAIN][0]) {
    d.setFont(FONT_BIG);
    const char* t = s.slots[SLOT_MAIN];
    int w = d.getStrWidth(t);
    if (w > W) draw_fit(g_ox, MAIN_TEXT_BASE + g_oy, t, W);
    else d.drawStr((W - w) / 2 + g_ox, MAIN_TEXT_BASE + g_oy, t);
  }
}

static void draw_detail(const HudState& s) {
  d.setFont(FONT_SMALL);
  draw_fit(g_ox, DETAIL_BASE + g_oy, s.slots[SLOT_DETAIL], W);
}

// ---------------------------------------------------------------- public

void renderer_begin(const HudConfig& cfg) {
  d.setBusClock(I2C_CLOCK_HZ);
  d.begin();
  d.setFontMode(1);   // transparent text background
  d.setDrawColor(1);
  renderer_apply_config(cfg);
}

void renderer_apply_config(const HudConfig& cfg) {
  g_ox = cfg.offset_x;
  g_oy = cfg.offset_y;
  // SSD1306 hardware mirroring (U8g2's normal orientation is A1 / C8).
  d.sendF("c", (cfg.flags & CFG_FLIP_H) ? 0xA0 : 0xA1);  // segment remap
  d.sendF("c", (cfg.flags & CFG_FLIP_V) ? 0xC0 : 0xC8);  // COM scan direction
  d.sendF("c", (cfg.flags & CFG_INVERT) ? 0xA7 : 0xA6);  // normal / inverse
  d.setContrast(cfg.contrast);
}

static void push_rows(int y0, int y1) {
  y0 += g_oy;
  y1 += g_oy;
  if (y0 < 0) y0 = 0;
  if (y1 > H - 1) y1 = H - 1;
  if (y1 < y0) return;
  const int p0 = y0 / 8, p1 = y1 / 8;
  d.updateDisplayArea(0, p0, W / 8, p1 - p0 + 1);
}

void renderer_draw(const HudState& s, bool connected, uint8_t dirty) {
  if (!dirty) return;
  // Re-drawing the whole 1 KB buffer in RAM is ~1 ms. The expensive part is
  // the I2C transfer, so we only push the pages that changed.
  d.clearBuffer();
  draw_status(s, connected);
  draw_main(s);
  draw_detail(s);

  if (dirty & DIRTY_CONFIG) {
    d.sendBuffer();
    return;
  }
  if (dirty & DIRTY_STATUS) push_rows(STATUS_Y0, STATUS_Y1);
  if (dirty & DIRTY_MAIN) push_rows(MAIN_Y0, MAIN_Y1);
  if (dirty & DIRTY_DETAIL) push_rows(DETAIL_Y0, DETAIL_Y1);
}

void renderer_set_panel(bool on) {
  if (on == g_panel_on) return;
  g_panel_on = on;
  d.setPowerSave(on ? 0 : 1);  // panel sleep: ~10 uA vs several mA lit
}

bool renderer_panel_on() { return g_panel_on; }
