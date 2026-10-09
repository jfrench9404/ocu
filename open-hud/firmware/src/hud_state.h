// Pure-C++ HUD state machine: turns wire frames into screen state.
// No Arduino / BLE / display dependencies, so it can be unit-tested on a PC.
#pragma once
#include <stddef.h>
#include <stdint.h>
#include "protocol.h"

struct HudConfig {
  uint8_t flags;      // proto::CFG_*
  int8_t offset_x;    // px, clamped to -32..32
  int8_t offset_y;
  uint8_t contrast;
  uint8_t sleep_s;    // 0 = never sleep the panel
};

// Dirty bits tell the renderer which screen regions changed.
enum : uint8_t {
  DIRTY_STATUS = 0x01,
  DIRTY_MAIN = 0x02,
  DIRTY_DETAIL = 0x04,
  DIRTY_CONFIG = 0x08,  // orientation/contrast changed -> full redraw + save
  DIRTY_ALL = 0x0F,
};

struct HudState {
  char slots[proto::SLOT_COUNT][proto::MAX_TEXT + 1];

  bool nav_active;
  uint8_t nav_arrow;
  uint16_t nav_distance_m;
  char nav_text[proto::MAX_TEXT + 1];

  bool notif_active;
  bool notif_has_ttl;
  uint8_t notif_app;
  uint32_t notif_expires_ms;
  char notif_title[proto::MAX_TEXT + 1];
  char notif_body[proto::MAX_TEXT + 1];

  HudConfig cfg;

  uint8_t last_seq;
  bool status_requested;  // set by PING; main loop sends STATUS and clears it
  uint8_t dirty;
};

void hud_init(HudState& s, const HudConfig& cfg);

// Apply one complete frame. Returns 0 on success or a proto::ERR_* code.
uint8_t hud_apply(HudState& s, const uint8_t* frame, size_t len, uint32_t now_ms);

// Time-based housekeeping (notification expiry). Call every loop.
void hud_tick(HudState& s, uint32_t now_ms);
