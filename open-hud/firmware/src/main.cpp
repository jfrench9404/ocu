// Open-HUD firmware entry point.
//
// Data flow:  BLE write -> static queue -> hud_apply() -> dirty bits ->
//             renderer_draw() pushes only the changed display pages.
//
// All memory is static: no malloc/new after setup().

#include <Arduino.h>
#include <Preferences.h>
#include <string.h>

#include "ble_link.h"
#include "config.h"
#include "hud_state.h"
#include "protocol.h"
#include "renderer.h"

using namespace proto;

static HudState g_state;
static Preferences g_prefs;
static uint32_t g_last_activity_ms = 0;
static bool g_was_connected = false;
static HudConfig g_saved_cfg;

// ---------------------------------------------------------------- config

static HudConfig load_config() {
  HudConfig c = {DEFAULT_FLAGS, DEFAULT_OFFSET_X, DEFAULT_OFFSET_Y, DEFAULT_CONTRAST,
                 DEFAULT_SLEEP_S};
  g_prefs.begin("openhud", true);
  if (g_prefs.getBytesLength("cfg") == sizeof(HudConfig)) {
    g_prefs.getBytes("cfg", &c, sizeof(HudConfig));
  }
  g_prefs.end();
  g_saved_cfg = c;
  return c;
}

static void save_config(const HudConfig& c) {
  if (memcmp(&c, &g_saved_cfg, sizeof(c)) == 0) return;  // spare the flash
  g_saved_cfg = c;
  g_prefs.begin("openhud", false);
  g_prefs.putBytes("cfg", &c, sizeof(HudConfig));
  g_prefs.end();
}

// ---------------------------------------------------------------- battery

static uint8_t battery_pct() {
#if PIN_BATTERY_ADC >= 0
  uint32_t mv = (uint32_t)(analogReadMilliVolts(PIN_BATTERY_ADC) * BATTERY_DIVIDER);
  if (mv <= BATTERY_EMPTY_MV) return 0;
  if (mv >= BATTERY_FULL_MV) return 100;
  return (uint8_t)((mv - BATTERY_EMPTY_MV) * 100 / (BATTERY_FULL_MV - BATTERY_EMPTY_MV));
#else
  return BATTERY_UNKNOWN;
#endif
}

static void send_status() {
  ble_send_status(g_state.last_seq, battery_pct(),
                  renderer_panel_on() ? STATUS_PANEL_ON : 0);
}

// ---------------------------------------------------------------- setup/loop

void setup() {
  setCpuFrequencyMhz(CPU_FREQ_MHZ);
  Serial.begin(115200);

  hud_init(g_state, load_config());
  strncpy(g_state.slots[SLOT_MAIN], "Open-HUD", MAX_TEXT);

  renderer_begin(g_state.cfg);
  renderer_draw(g_state, false, DIRTY_ALL);
  g_state.dirty = 0;

  ble_begin();
  g_last_activity_ms = millis();
  Serial.println("[openhud] ready, advertising");
}

void loop() {
  RxFrame f;
  bool got_frame = false;

  // Block for up to 50 ms waiting for data; the CPU idles meanwhile.
  if (ble_receive(f, 50)) {
    // Drain everything queued so a burst of updates costs one redraw.
    do {
      uint8_t err = hud_apply(g_state, f.data, f.len, millis());
      if (err) ble_send_error(f.len >= 2 ? f.data[1] : 0, err);
      got_frame = true;
    } while (ble_receive(f, 0));
  }

  const uint32_t now = millis();
  hud_tick(g_state, now);

  if (ble_take_overflow()) ble_send_error(g_state.last_seq, ERR_QUEUE_FULL);

  // Connection state shows in the status bar.
  const bool connected = ble_connected();
  if (connected != g_was_connected) {
    g_was_connected = connected;
    g_state.dirty |= DIRTY_STATUS;
    if (connected) got_frame = true;  // wake the panel on reconnect
  }

  if (ble_take_subscribe_event() || g_state.status_requested) {
    g_state.status_requested = false;
    send_status();
  }

  // Panel power management.
  uint8_t force = 0;
  if (got_frame) {
    g_last_activity_ms = now;
    if (!renderer_panel_on()) {
      renderer_set_panel(true);
      force = DIRTY_CONFIG;  // full push after waking the panel
    }
  } else if (renderer_panel_on() && g_state.cfg.sleep_s &&
             now - g_last_activity_ms > (uint32_t)g_state.cfg.sleep_s * 1000u) {
    renderer_set_panel(false);
  }

  if (g_state.dirty & DIRTY_CONFIG) {
    renderer_apply_config(g_state.cfg);
    save_config(g_state.cfg);
  }
  if ((g_state.dirty | force) && renderer_panel_on()) {
    renderer_draw(g_state, connected, g_state.dirty | force);
    g_state.dirty = 0;
  }

  ble_service(now);
}
