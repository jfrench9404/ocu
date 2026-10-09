// Open-HUD wire protocol v1 — must match docs/PROTOCOL.md and
// host/openhud/protocol.py (checked by host/tests/test_protocol_sync.py).
#pragma once
#include <stdint.h>

#define OPENHUD_DEVICE_NAME  "OpenHUD"
#define OPENHUD_SERVICE_UUID "6f70656e-6875-6400-0001-000000000000"
#define OPENHUD_RX_UUID      "6f70656e-6875-6400-0002-000000000000"
#define OPENHUD_TX_UUID      "6f70656e-6875-6400-0003-000000000000"

namespace proto {

constexpr uint8_t PROTOCOL_VERSION = 1;
constexpr uint8_t FW_VERSION = 1;

constexpr uint8_t MAX_FRAME = 64;
constexpr uint8_t HEADER_LEN = 3;
constexpr uint8_t MAX_PAYLOAD = 61;
constexpr uint8_t MAX_TEXT = 60;
constexpr uint8_t NOTIFY_SEP = 0x1F;

// Host -> glasses
constexpr uint8_t MSG_CLEAR = 0x01;
constexpr uint8_t MSG_TEXT = 0x02;
constexpr uint8_t MSG_NAV = 0x03;
constexpr uint8_t MSG_NOTIFY = 0x04;
constexpr uint8_t MSG_CONFIG = 0x05;
constexpr uint8_t MSG_PING = 0x06;
constexpr uint8_t MSG_DISMISS = 0x07;

// Glasses -> host
constexpr uint8_t MSG_STATUS = 0x81;
constexpr uint8_t MSG_ERROR = 0x82;

// Text slots
constexpr uint8_t SLOT_STATUS_L = 0;
constexpr uint8_t SLOT_STATUS_R = 1;
constexpr uint8_t SLOT_MAIN = 2;
constexpr uint8_t SLOT_DETAIL = 3;
constexpr uint8_t SLOT_COUNT = 4;

// Nav arrows
constexpr uint8_t ARROW_NONE = 0;
constexpr uint8_t ARROW_STRAIGHT = 1;
constexpr uint8_t ARROW_SLIGHT_RIGHT = 2;
constexpr uint8_t ARROW_RIGHT = 3;
constexpr uint8_t ARROW_SHARP_RIGHT = 4;
constexpr uint8_t ARROW_UTURN = 5;
constexpr uint8_t ARROW_SHARP_LEFT = 6;
constexpr uint8_t ARROW_LEFT = 7;
constexpr uint8_t ARROW_SLIGHT_LEFT = 8;
constexpr uint8_t ARROW_ARRIVE = 9;

constexpr uint16_t DISTANCE_HIDDEN = 0xFFFF;

// Notification apps
constexpr uint8_t APP_GENERIC = 0;
constexpr uint8_t APP_CALL = 1;
constexpr uint8_t APP_MESSAGE = 2;
constexpr uint8_t APP_EMAIL = 3;
constexpr uint8_t APP_CALENDAR = 4;
constexpr uint8_t APP_AI = 5;

// CONFIG flags
constexpr uint8_t CFG_FLIP_H = 0x01;
constexpr uint8_t CFG_FLIP_V = 0x02;
constexpr uint8_t CFG_INVERT = 0x04;

// STATUS flags
constexpr uint8_t STATUS_PANEL_ON = 0x01;
constexpr uint8_t BATTERY_UNKNOWN = 0xFF;

// ERROR codes
constexpr uint8_t ERR_BAD_LENGTH = 1;
constexpr uint8_t ERR_UNKNOWN_TYPE = 2;
constexpr uint8_t ERR_BAD_SLOT = 3;
constexpr uint8_t ERR_QUEUE_FULL = 4;

}  // namespace proto
