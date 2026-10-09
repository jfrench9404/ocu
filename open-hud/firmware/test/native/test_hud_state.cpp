// Host-side test of the firmware state machine (no ESP32 needed):
//   g++ -std=c++17 -I../../src test_hud_state.cpp ../../src/hud_state.cpp -o t && ./t
#include <assert.h>
#include <stdio.h>
#include <string.h>

#include <initializer_list>

#include "hud_state.h"

using namespace proto;

static HudState s;

static uint8_t send(std::initializer_list<uint8_t> bytes, uint32_t now = 0) {
  uint8_t buf[MAX_FRAME];
  size_t n = 0;
  for (uint8_t b : bytes) buf[n++] = b;
  return hud_apply(s, buf, n, now);
}

int main() {
  hud_init(s, HudConfig{0, 0, 0, 200, 60});
  s.dirty = 0;

  assert(send({MSG_TEXT, 1, 3, SLOT_MAIN, 'H', 'i'}) == 0);
  assert(strcmp(s.slots[SLOT_MAIN], "Hi") == 0);
  assert(s.dirty == DIRTY_MAIN && s.last_seq == 1);

  assert(send({MSG_TEXT, 2, 2, SLOT_DETAIL, 0x07}) == 0);  // control char -> '?'
  assert(strcmp(s.slots[SLOT_DETAIL], "?") == 0);

  assert(send({MSG_TEXT, 0, 2, 9, 'x'}) == ERR_BAD_SLOT);
  assert(send({MSG_TEXT, 0, 9, 1}) == ERR_BAD_LENGTH);
  assert(send({0x55, 0, 0}) == ERR_UNKNOWN_TYPE);

  assert(send({MSG_NAV, 3, 5, ARROW_LEFT, 0xD2, 0x04, 'E', 'l'}) == 0);
  assert(s.nav_active && s.nav_arrow == ARROW_LEFT && s.nav_distance_m == 1234);
  assert(send({MSG_NAV, 4, 3, ARROW_NONE, 0xFF, 0xFF}) == 0 && !s.nav_active);

  assert(send({MSG_NOTIFY, 5, 7, APP_CALL, 2, 'M', 'o', 'm', NOTIFY_SEP, 'x'}, 1000) == 0);
  assert(s.notif_active && strcmp(s.notif_title, "Mom") == 0 && strcmp(s.notif_body, "x") == 0);
  hud_tick(s, 2999);
  assert(s.notif_active);
  hud_tick(s, 3000);
  assert(!s.notif_active);

  // TTL across millis() wrap-around
  assert(send({MSG_NOTIFY, 6, 3, APP_AI, 1, 'A'}, 0xFFFFFF00u) == 0);
  hud_tick(s, 0xFFFFFF10u);
  assert(s.notif_active);
  hud_tick(s, 0x000002F0u);
  assert(!s.notif_active);

  assert(send({MSG_CONFIG, 7, 5, CFG_FLIP_H, (uint8_t)-40, 5, 100, 0}) == 0);
  assert(s.cfg.flags == CFG_FLIP_H && s.cfg.offset_x == -32 && s.cfg.offset_y == 5);

  assert(send({MSG_PING, 8, 0}) == 0 && s.status_requested);

  assert(send({MSG_CLEAR, 9, 0}) == 0);
  assert(s.slots[SLOT_MAIN][0] == '\0');

  puts("hud_state: all tests passed");
  return 0;
}
