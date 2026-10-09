#include "hud_state.h"

#include <string.h>

using namespace proto;

// Copy wire text into a fixed buffer, NUL-terminate, replace non-printables.
static void copy_text(char* dst, const uint8_t* src, size_t n) {
  if (n > MAX_TEXT) n = MAX_TEXT;
  for (size_t i = 0; i < n; i++) {
    uint8_t c = src[i];
    dst[i] = (c >= 0x20 && c <= 0x7E) ? (char)c : '?';
  }
  dst[n] = '\0';
}

static int8_t clamp_offset(int8_t v) {
  if (v < -32) return -32;
  if (v > 32) return 32;
  return v;
}

void hud_init(HudState& s, const HudConfig& cfg) {
  memset(&s, 0, sizeof(s));
  s.cfg = cfg;
  s.cfg.offset_x = clamp_offset(cfg.offset_x);
  s.cfg.offset_y = clamp_offset(cfg.offset_y);
  s.nav_distance_m = DISTANCE_HIDDEN;
  s.dirty = DIRTY_ALL;
}

uint8_t hud_apply(HudState& s, const uint8_t* f, size_t len, uint32_t now_ms) {
  if (len < HEADER_LEN || len > MAX_FRAME) return ERR_BAD_LENGTH;
  const uint8_t type = f[0];
  const uint8_t seq = f[1];
  const size_t plen = f[2];
  if (HEADER_LEN + plen != len) return ERR_BAD_LENGTH;
  const uint8_t* p = f + HEADER_LEN;
  s.last_seq = seq;

  switch (type) {
    case MSG_CLEAR:
      for (auto& slot : s.slots) slot[0] = '\0';
      s.nav_active = false;
      s.nav_text[0] = '\0';
      s.notif_active = false;
      s.dirty |= DIRTY_STATUS | DIRTY_MAIN | DIRTY_DETAIL;
      return 0;

    case MSG_TEXT: {
      if (plen < 1) return ERR_BAD_LENGTH;
      const uint8_t slot = p[0];
      if (slot >= SLOT_COUNT) return ERR_BAD_SLOT;
      copy_text(s.slots[slot], p + 1, plen - 1);
      if (slot == SLOT_STATUS_L || slot == SLOT_STATUS_R) s.dirty |= DIRTY_STATUS;
      else if (slot == SLOT_MAIN) s.dirty |= DIRTY_MAIN;
      else s.dirty |= DIRTY_DETAIL;
      return 0;
    }

    case MSG_NAV:
      if (plen < 3) return ERR_BAD_LENGTH;
      s.nav_arrow = p[0];
      s.nav_active = (p[0] != ARROW_NONE);
      s.nav_distance_m = (uint16_t)(p[1] | (p[2] << 8));
      copy_text(s.nav_text, p + 3, plen - 3);
      s.dirty |= DIRTY_MAIN;
      return 0;

    case MSG_NOTIFY: {
      if (plen < 2) return ERR_BAD_LENGTH;
      s.notif_app = p[0];
      const uint8_t ttl = p[1];
      const uint8_t* text = p + 2;
      const size_t tlen = plen - 2;
      size_t sep = tlen;
      for (size_t i = 0; i < tlen; i++) {
        if (text[i] == NOTIFY_SEP) { sep = i; break; }
      }
      copy_text(s.notif_title, text, sep);
      if (sep < tlen) copy_text(s.notif_body, text + sep + 1, tlen - sep - 1);
      else s.notif_body[0] = '\0';
      s.notif_has_ttl = ttl > 0;
      s.notif_expires_ms = now_ms + (uint32_t)ttl * 1000u;
      s.notif_active = true;
      s.dirty |= DIRTY_MAIN;
      return 0;
    }

    case MSG_CONFIG:
      if (plen != 5) return ERR_BAD_LENGTH;
      s.cfg.flags = p[0];
      s.cfg.offset_x = clamp_offset((int8_t)p[1]);
      s.cfg.offset_y = clamp_offset((int8_t)p[2]);
      s.cfg.contrast = p[3];
      s.cfg.sleep_s = p[4];
      s.dirty |= DIRTY_ALL;
      return 0;

    case MSG_PING:
      s.status_requested = true;
      return 0;

    case MSG_DISMISS:
      if (s.notif_active) {
        s.notif_active = false;
        s.dirty |= DIRTY_MAIN;
      }
      return 0;

    default:
      return ERR_UNKNOWN_TYPE;
  }
}

void hud_tick(HudState& s, uint32_t now_ms) {
  // Signed difference handles millis() wrap-around (~49 days).
  if (s.notif_active && s.notif_has_ttl &&
      (int32_t)(now_ms - s.notif_expires_ms) >= 0) {
    s.notif_active = false;
    s.dirty |= DIRTY_MAIN;
  }
}
