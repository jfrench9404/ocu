// Draws HudState onto an SSD1306 using U8g2 with a static 1 KB frame buffer.
// Only the 8-pixel "pages" that changed are pushed over I2C.
#pragma once
#include "hud_state.h"

// Layout (128x64, before user offset). Mirrored in host/openhud/sim/render.py.
namespace layout {
constexpr int W = 128;
constexpr int H = 64;
constexpr int STATUS_Y0 = 0, STATUS_Y1 = 9, STATUS_BASE = 7;
constexpr int MAIN_Y0 = 11, MAIN_Y1 = 52;
constexpr int DETAIL_Y0 = 53, DETAIL_Y1 = 63, DETAIL_BASE = 63;
constexpr int MAIN_TEXT_BASE = 38;
constexpr int ARROW_CX = 20, ARROW_CY = 32;
constexpr int NAV_TEXT_X = 44, NAV_DIST_BASE = 32, NAV_STREET_BASE = 47;
constexpr int NOTIF_ICON_X = 0, NOTIF_ICON_Y = 13, NOTIF_ICON_S = 15;
constexpr int NOTIF_TITLE_X = 19, NOTIF_TITLE_BASE = 25;
constexpr int NOTIF_BODY_BASE1 = 39, NOTIF_BODY_BASE2 = 50;
constexpr int SMALL_CHARS_PER_LINE = 21;  // 6x10 font
}  // namespace layout

void renderer_begin(const HudConfig& cfg);
void renderer_apply_config(const HudConfig& cfg);
void renderer_draw(const HudState& s, bool connected, uint8_t dirty);
void renderer_set_panel(bool on);
bool renderer_panel_on();

// Format metres as "350 m", "1.2 km", "12 km" (mirrored in the simulator).
void format_distance(uint16_t m, char* out, size_t n);
