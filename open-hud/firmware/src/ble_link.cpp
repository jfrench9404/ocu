#include "ble_link.h"

#include <Arduino.h>
#include <NimBLEDevice.h>
#include <freertos/FreeRTOS.h>
#include <freertos/queue.h>
#include <string.h>

#include "config.h"

using namespace proto;

static constexpr int QUEUE_DEPTH = 16;
static StaticQueue_t g_queue_ctrl;
static uint8_t g_queue_storage[QUEUE_DEPTH * sizeof(RxFrame)];
static QueueHandle_t g_queue = nullptr;

static NimBLEServer* g_server = nullptr;
static NimBLECharacteristic* g_tx = nullptr;

static volatile bool g_connected = false;
static volatile bool g_subscribed_event = false;
static volatile bool g_overflow = false;
static volatile bool g_adv_fast = false;
static volatile uint32_t g_adv_started_ms = 0;

static void start_advertising(bool fast) {
  NimBLEAdvertising* adv = NimBLEDevice::getAdvertising();
  adv->stop();
  if (fast) {
    adv->setMinInterval(BLE_ADV_FAST_MIN);
    adv->setMaxInterval(BLE_ADV_FAST_MAX);
  } else {
    adv->setMinInterval(BLE_ADV_SLOW_MIN);
    adv->setMaxInterval(BLE_ADV_SLOW_MAX);
  }
  adv->start();
  g_adv_fast = fast;
  g_adv_started_ms = millis();
}

class ServerCallbacks : public NimBLEServerCallbacks {
  void onConnect(NimBLEServer* s, ble_gap_conn_desc* desc) override {
    g_connected = true;
    // Ask the phone for a 30-60 ms interval, no slave latency.
    s->updateConnParams(desc->conn_handle, BLE_CONN_MIN_INTERVAL, BLE_CONN_MAX_INTERVAL, 0,
                        BLE_CONN_TIMEOUT);
  }
  void onDisconnect(NimBLEServer*) override {
    g_connected = false;
    start_advertising(true);  // fast advertising => reconnect in well under 2 s
  }
};

class RxCallbacks : public NimBLECharacteristicCallbacks {
  void onWrite(NimBLECharacteristic* c) override {
    NimBLEAttValue v = c->getValue();
    RxFrame f;
    size_t n = v.length();
    if (n > MAX_FRAME) n = MAX_FRAME;  // hud_apply will flag the bad length
    f.len = (uint8_t)n;
    memcpy(f.data, v.data(), n);
    if (xQueueSend(g_queue, &f, 0) != pdTRUE) g_overflow = true;
  }
};

class TxCallbacks : public NimBLECharacteristicCallbacks {
  void onSubscribe(NimBLECharacteristic*, ble_gap_conn_desc*, uint16_t sub_value) override {
    if (sub_value & 0x0001) g_subscribed_event = true;
  }
};

static ServerCallbacks g_server_cb;
static RxCallbacks g_rx_cb;
static TxCallbacks g_tx_cb;

void ble_begin() {
  g_queue = xQueueCreateStatic(QUEUE_DEPTH, sizeof(RxFrame), g_queue_storage, &g_queue_ctrl);

  NimBLEDevice::init(OPENHUD_DEVICE_NAME);
  NimBLEDevice::setMTU(185);  // need >= 67 for a 64-byte frame

  g_server = NimBLEDevice::createServer();
  g_server->setCallbacks(&g_server_cb, false);
  g_server->advertiseOnDisconnect(false);  // we restart it ourselves (fast)

  NimBLEService* svc = g_server->createService(OPENHUD_SERVICE_UUID);
  NimBLECharacteristic* rx = svc->createCharacteristic(
      OPENHUD_RX_UUID, NIMBLE_PROPERTY::WRITE | NIMBLE_PROPERTY::WRITE_NR, MAX_FRAME);
  rx->setCallbacks(&g_rx_cb);
  g_tx = svc->createCharacteristic(OPENHUD_TX_UUID, NIMBLE_PROPERTY::NOTIFY, 8);
  g_tx->setCallbacks(&g_tx_cb);
  svc->start();

  NimBLEAdvertising* adv = NimBLEDevice::getAdvertising();
  adv->addServiceUUID(OPENHUD_SERVICE_UUID);
  adv->setScanResponse(true);  // device name goes in the scan response
  start_advertising(true);
}

bool ble_receive(RxFrame& out, uint32_t timeout_ms) {
  return xQueueReceive(g_queue, &out, pdMS_TO_TICKS(timeout_ms)) == pdTRUE;
}

bool ble_connected() { return g_connected; }

bool ble_take_subscribe_event() {
  if (!g_subscribed_event) return false;
  g_subscribed_event = false;
  return true;
}

bool ble_take_overflow() {
  if (!g_overflow) return false;
  g_overflow = false;
  return true;
}

static void notify(const uint8_t* data, size_t len) {
  if (!g_connected || !g_tx) return;
  g_tx->setValue(data, len);
  g_tx->notify();
}

void ble_send_status(uint8_t last_seq, uint8_t battery_pct, uint8_t flags) {
  const uint8_t f[] = {MSG_STATUS, 0, 4, last_seq, battery_pct, flags, FW_VERSION};
  notify(f, sizeof(f));
}

void ble_send_error(uint8_t seq, uint8_t code) {
  const uint8_t f[] = {MSG_ERROR, 0, 2, seq, code};
  notify(f, sizeof(f));
}

void ble_service(uint32_t now_ms) {
  if (!g_connected && g_adv_fast && now_ms - g_adv_started_ms > BLE_ADV_FAST_WINDOW_MS) {
    start_advertising(false);
  }
}
