# Open-HUD

Clip-on monocular HUD for any pair of glasses. An ESP32-C3 drives a small
monochrome OLED through your optical combiner, and a host app (Python for
now, phone later) sends it tiny pre-digested updates over Bluetooth LE.

```
 phone / laptop (Python host)                         glasses (ESP32-C3)
 ┌───────────────────────────────────────────┐        ┌──────────────────────────────┐
 │ sources ─▶ EventBus ─▶ Preprocessor ─▶ HudLink ──BLE──▶ queue ─▶ hud_state ─▶ renderer │
 │ (notifs,     (pub/sub)   (ASCII, trunc,   (latest-wins,  ≤64 B  (static) (switch)  (dirty pages │
 │  nav, AI,                 arrows, km)      reconnect +    frames                     over I2C)  │
 │  clock)                                    replay, ping)                                         │
 └───────────────────────────────────────────┘        └──────────────────────────────┘
```

## Repo layout

| Path | What |
|---|---|
| `docs/PROTOCOL.md` | Wire protocol v1 — the source of truth |
| `firmware/` | PlatformIO project for ESP32-C3 + SSD1306 128×64 (U8g2 + NimBLE) |
| `firmware/test/native/` | PC-side test of the firmware state machine |
| `host/openhud/` | Python host: events, preprocessing, BLE link, simulator, CLI |
| `host/tests/` | pytest suite (includes a check that C and Python constants match) |

## Try it with no hardware

```bash
cd host
pip install -e ".[dev]"
python -m openhud demo --out sim_frames   # writes a PNG per screen change
pytest
```

## Hardware (prototype)

- Seeed XIAO ESP32C3 (or any ESP32-C3 board — see `platformio.ini`)
- SSD1306 128×64 I²C OLED (0.96", 0.49" or 0.42" modules all work)
- 100–150 mAh LiPo (the XIAO has a charger built in)

| OLED | XIAO ESP32C3 |
|---|---|
| VCC | 3V3 |
| GND | GND |
| SDA | D4 (GPIO6) |
| SCL | D5 (GPIO7) |

Pins, battery sense, BLE timing and power defaults are all in
`firmware/src/config.h`.

## Flash and run

```bash
cd firmware
pio run -t upload && pio device monitor

cd ../host
python -m openhud ping --ble                          # find glasses, measure latency
python -m openhud config --flip-h --offset-x 4 --ble  # match your combiner / eye box
python -m openhud notify "Sam" "Running late" --ble
python -m openhud demo --ble
```

## Using it from your own code

```python
import asyncio
from openhud import Hud, events as ev
from openhud.transport import BleTransport

async def main():
    async with Hud(BleTransport()) as hud:
        await hud.link.connected_event.wait()
        await hud.publish(ev.NavUpdate("turn left", 230, "North Main Street"))
        await hud.publish(ev.Notification("message", "Sam", "Grab a table?"))

asyncio.run(main())
```

## How the design targets are handled

| Target | How |
|---|---|
| < 100 ms latency | Write-without-response, 30–60 ms connection interval with zero slave latency, firmware blocks on a queue (wakes instantly), only changed display pages are pushed. Measure with `openhud ping`. |
| ≤ 64 B frames | Enforced in `protocol.py`; tested for every message type. |
| Static RAM < 30 KB | No heap use after setup: 1 KB frame buffer, 16×65 B queue, ~0.4 KB state. (The NimBLE stack itself needs more; see the build's RAM report.) |
| Pure-black canvas | Nothing is ever drawn as a background; empty screen renders with zero lit pixels (tested). |
| Reconnect < 2 s | Glasses advertise every 20–30 ms for 30 s after a drop; host retries with 0.1→2 s backoff and reconnects by cached address, then replays the current screen. |
| Optics | Hardware mirror (SSD1306 segment/COM remap), X/Y offset, contrast — saved to flash. |
| 8 h on 100–150 mAh | Panel sleeps after idle, 80 MHz CPU, dirty-page updates. Not yet measured; see below. |

## Known gaps / next steps

- **Firmware hasn't been compiled for the C3 yet** in this environment (the
  PlatformIO registry was unreachable). The library calls were checked
  against NimBLE-Arduino 1.4.3 and U8g2 sources, and the state machine is
  tested natively — run `pio run` first and expect a small fix or two.
- Power: enable ESP-IDF automatic light sleep (needs a custom sdkconfig or
  the ESP-IDF framework) and measure real current draw.
- Negative X/Y offsets: confirm on hardware that text near the left/top edge
  clips cleanly.
- Lens distortion correction and an on-glasses alignment grid (needs a
  small bitmap/primitive message type).
- Mobile host: port `preprocess.py` + `link.py` to Android (Kotlin) for real
  notification access and Mapbox/OSM navigation.
- Bonding/encryption so other phones can't push to your glasses.
