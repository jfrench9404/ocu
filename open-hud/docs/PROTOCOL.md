# Open-HUD Wire Protocol (v1)

This file is the source of truth. `firmware/src/protocol.h` and
`host/openhud/protocol.py` must match it; `host/tests/test_protocol_sync.py`
checks that the C and Python constants agree.

## Design rules

- **One frame = one BLE write.** Every frame is at most **64 bytes** and is sent
  as a single *Write Without Response*. The host negotiates an ATT MTU of at
  least 67 (64 + 3 bytes ATT overhead). No fragmentation, no reassembly.
- **The phone does the thinking.** All text arrives pre-truncated, ASCII-only,
  and already assigned to a screen slot. The microcontroller copies bytes into
  fixed buffers and redraws. No JSON, no heap, no parsing beyond a switch.
- **Latest wins.** Frames are idempotent state updates ("slot MAIN now says X"),
  not commands that depend on history. A dropped frame is fixed by the next one.
- Multi-byte integers are **little-endian**.

## BLE GATT layout

| Item | UUID | Properties |
|---|---|---|
| Service | `6f70656e-6875-6400-0001-000000000000` | |
| RX (host → glasses) | `6f70656e-6875-6400-0002-000000000000` | Write, Write Without Response |
| TX (glasses → host) | `6f70656e-6875-6400-0003-000000000000` | Notify |

Advertised name: `OpenHUD`. The service UUID is in the advertising packet so
the host can scan-filter on it.

## Frame layout

```
 byte 0      byte 1     byte 2      bytes 3 .. 3+len-1
+---------+----------+-----------+-----------------------+
|  type   |   seq    |   len     |   payload (0..61 B)   |
+---------+----------+-----------+-----------------------+
```

- `type` — message type (table below).
- `seq` — rolling 0..255 counter set by the sender; echoed in STATUS so the host
  can measure round-trip latency.
- `len` — payload length. `3 + len` must equal the BLE write length.

## Host → glasses messages

| Type | Name | Payload |
|---|---|---|
| `0x01` | CLEAR | *(none)* — blank all slots, end nav, drop notification |
| `0x02` | TEXT | `slot:u8`, `text[]` (≤ 60 ASCII bytes) |
| `0x03` | NAV | `arrow:u8`, `distance_m:u16`, `text[]` (≤ 58) — `arrow=0` ends nav mode; `distance_m=0xFFFF` hides distance |
| `0x04` | NOTIFY | `app:u8`, `ttl_s:u8`, `text[]` (≤ 59) — title and body separated by `0x1F`; overlays the main area for `ttl_s` seconds (0 = until DISMISS) |
| `0x05` | CONFIG | `flags:u8`, `offset_x:i8`, `offset_y:i8`, `contrast:u8`, `sleep_s:u8` |
| `0x06` | PING | *(none)* — glasses reply with STATUS |
| `0x07` | DISMISS | *(none)* — remove the active notification |

### Slots (TEXT)

| Value | Slot | Where on a 128×64 panel | Max visible chars |
|---|---|---|---|
| 0 | STATUS_L | top bar, left | 12 |
| 1 | STATUS_R | top bar, right | 8 |
| 2 | MAIN | centre, large font | 12 |
| 3 | DETAIL | bottom line, small font | 21 |

Writing to MAIN while nav is active is stored but hidden until nav ends.

### Arrows (NAV)

| 0 NONE (end nav) | 1 STRAIGHT | 2 SLIGHT_RIGHT | 3 RIGHT | 4 SHARP_RIGHT |
|---|---|---|---|---|
| **5 UTURN** | **6 SHARP_LEFT** | **7 LEFT** | **8 SLIGHT_LEFT** | **9 ARRIVE** |

### Apps (NOTIFY)

`0 GENERIC`, `1 CALL`, `2 MESSAGE`, `3 EMAIL`, `4 CALENDAR`, `5 AI`.

### CONFIG flags

| Bit | Meaning |
|---|---|
| 0 | flip horizontal (mirror — typical for a single reflective combiner) |
| 1 | flip vertical |
| 2 | invert colours (debug only — lit background burns power) |

`offset_x` / `offset_y` shift the whole layout in pixels (−32..32) to centre
the image in the wearer's eye box. `contrast` is 0–255. `sleep_s` turns the
panel off after that many seconds with no new frame (0 = never). CONFIG is
saved to flash on the glasses and survives power cycles.

## Glasses → host messages (notify on TX)

| Type | Name | Payload |
|---|---|---|
| `0x81` | STATUS | `last_seq:u8`, `battery_pct:u8` (0xFF = unknown), `flags:u8` (bit0 = panel on), `fw_version:u8` |
| `0x82` | ERROR | `seq:u8`, `code:u8` (1 = bad length, 2 = unknown type, 3 = bad slot, 4 = queue full) |

STATUS is sent once on connect and in reply to every PING.

## Text rules

Printable ASCII only (`0x20`–`0x7E`), plus `0x1F` as the NOTIFY separator.
The host folds accents and drops anything else; the glasses replace any
other byte with `?`. Text is not NUL-terminated on the wire.
