// BLE peripheral: one RX characteristic (frames in), one TX (status out).
// Incoming writes are copied into a static FreeRTOS queue from the BLE task;
// the main loop drains it. No heap allocation per frame.
#pragma once
#include <stddef.h>
#include <stdint.h>
#include "protocol.h"

struct RxFrame {
  uint8_t len;
  uint8_t data[proto::MAX_FRAME];
};

void ble_begin();

// Wait up to timeout_ms for a frame. Returns true if one was received.
bool ble_receive(RxFrame& out, uint32_t timeout_ms);

bool ble_connected();

// True once per subscribe event — the host just started listening.
bool ble_take_subscribe_event();

// True once if the queue overflowed since the last call.
bool ble_take_overflow();

void ble_send_status(uint8_t last_seq, uint8_t battery_pct, uint8_t flags);
void ble_send_error(uint8_t seq, uint8_t code);

// Call every loop: switches advertising from fast to slow after a while.
void ble_service(uint32_t now_ms);
