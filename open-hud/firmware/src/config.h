// Board / hardware configuration. Edit this file to match your wiring.
#pragma once

// ---- Display (SSD1306 128x64 over I2C) ----
// XIAO ESP32C3: SDA = D4 (GPIO6), SCL = D5 (GPIO7)
#ifndef PIN_I2C_SDA
#define PIN_I2C_SDA 6
#endif
#ifndef PIN_I2C_SCL
#define PIN_I2C_SCL 7
#endif
// 400 kHz is safe everywhere. Many SSD1306 modules run fine at 800k-1MHz,
// which roughly halves the time spent pushing pixels (= less power).
#define I2C_CLOCK_HZ 400000

// ---- Battery sense ----
// GPIO with a 1:2 resistor divider from the LiPo (e.g. 2x 220k), or -1 if
// not wired. The XIAO ESP32C3 has no built-in battery sense.
#define PIN_BATTERY_ADC  -1
#define BATTERY_DIVIDER  2.0f
#define BATTERY_EMPTY_MV 3300
#define BATTERY_FULL_MV  4200

// ---- Power ----
// BLE needs at least 80 MHz on the C3; 160 MHz buys nothing for this workload.
#define CPU_FREQ_MHZ 80

// ---- BLE timing (units noted) ----
// Connection interval in 1.25 ms units. 24..48 = 30..60 ms. Lower = snappier
// but more radio wake-ups. Slave latency stays 0 so host writes are never
// delayed by skipped connection events (keeps us under the 100 ms budget).
#define BLE_CONN_MIN_INTERVAL 24
#define BLE_CONN_MAX_INTERVAL 48
#define BLE_CONN_TIMEOUT      400   // 10 ms units -> 4 s supervision timeout

// Advertising interval in 0.625 ms units.
// Fast for the first 30 s after a disconnect (quick reconnects), then slow.
#define BLE_ADV_FAST_MIN 32         // 20 ms
#define BLE_ADV_FAST_MAX 48         // 30 ms
#define BLE_ADV_SLOW_MIN 1600       // 1 s
#define BLE_ADV_SLOW_MAX 1760       // 1.1 s
#define BLE_ADV_FAST_WINDOW_MS 30000

// ---- Defaults (overridden by a CONFIG frame, which is saved to flash) ----
#define DEFAULT_FLAGS     0x00
#define DEFAULT_OFFSET_X  0
#define DEFAULT_OFFSET_Y  0
#define DEFAULT_CONTRAST  200
#define DEFAULT_SLEEP_S   60
