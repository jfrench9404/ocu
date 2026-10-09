"""Command line: `python -m openhud <command> [--sim | --ble]`.

Examples
  python -m openhud demo --sim --out frames/       # no hardware: writes PNGs
  python -m openhud demo --ble                     # real glasses
  python -m openhud text "Hello" --ble
  python -m openhud notify "Mom" "Call me when you land" --app message --ble
  python -m openhud config --flip-h --offset-x 4 --ble
  python -m openhud ping --ble
"""
from __future__ import annotations

import argparse
import asyncio
import logging
import os
import time

from . import events as ev
from . import protocol as p
from .hud import Hud, clock_source
from .sim import SimDevice, preview, render
from .transport import BleTransport, SimTransport


class SimRecorder:
    """Saves a PNG every time the simulated screen changes."""

    def __init__(self, device: SimDevice, out_dir: str | None, scale: int = 5) -> None:
        self.device, self.out_dir, self.scale = device, out_dir, scale
        self.n = 0
        self._last = None
        if out_dir:
            os.makedirs(out_dir, exist_ok=True)
        device.on_change = self.snapshot

    def snapshot(self, label: str = "") -> None:
        img = render(self.device.state, self.device.connected)
        if self._last is not None and img.tobytes() == self._last:
            return
        self._last = img.tobytes()
        self.n += 1
        if self.out_dir:
            name = f"{self.n:03d}{'_' + label if label else ''}.png"
            preview(img, self.scale).save(os.path.join(self.out_dir, name))


SIM_SPEEDUP = 20  # demo runs 20x faster in the simulator unless --realtime


def _fast(args) -> bool:
    return args.cmd == "demo" and not args.ble and not args.realtime


def _make_transport(args):
    if args.ble:
        return BleTransport(address=args.address), None
    speed = SIM_SPEEDUP if _fast(args) else 1
    dev = SimDevice(clock=lambda: time.monotonic() * speed)
    rec = SimRecorder(dev, getattr(args, "out", None) or "sim_frames")
    return SimTransport(dev), rec


async def _demo(hud: Hud, fast: bool) -> None:
    pause = (lambda s: asyncio.sleep(s / (SIM_SPEEDUP if fast else 1)))
    hud.add_source(clock_source)
    await hud.publish(ev.StatusText(right="87%"))
    await hud.publish(ev.MainText("Good morning"))
    await hud.publish(ev.DetailText("Coffee w/ Sam at 9:30"))
    await pause(2)

    route = [
        ("depart", 450, "Woodward Avenue"),
        ("right", 120, "West Grand Boulevard"),
        ("right", 40, "West Grand Boulevard"),
        ("slight left", 800, "John C Lodge Freeway"),
        ("sharp left", 60, "Cass Avenue"),
        ("uturn", 30, "Cass Avenue"),
        ("arrive", 15, "Cafe Mocha"),
    ]
    for i, (m, d, street) in enumerate(route):
        await hud.publish(ev.NavUpdate(m, d, street))
        await pause(1.2)
        if i == 2:
            await hud.publish(ev.Notification("message", "Sam", "Running 5 min late, grab a table?", ttl_s=3))
            await pause(3.5)
    await hud.publish(ev.NavEnd())

    await hud.publish(ev.Notification("call", "Incoming call", "Mom - mobile", ttl_s=0))
    await pause(2)
    await hud.publish(ev.Dismiss())

    answer = "Your next meeting is the design review at 11:00 in Room 4B with Priya and Tom."
    for word in answer.split(" "):
        await hud.publish(ev.LlmChunk(word + " ", title="Assistant"))
        await pause(0.08)
    await hud.publish(ev.LlmChunk("", done=True, title="Assistant"))
    await pause(2)


async def amain(args) -> None:
    transport, rec = _make_transport(args)
    ticker = None
    if rec:  # the simulator needs a heartbeat for notification timeouts
        async def tick():
            while True:
                rec.device.tick()
                await asyncio.sleep(0.01)
        ticker = asyncio.create_task(tick())
    async with Hud(transport) as hud:
        await asyncio.wait_for(hud.link.connected_event.wait(), timeout=30)
        if args.cmd == "demo":
            await _demo(hud, fast=_fast(args))
        elif args.cmd == "text":
            slot = {"main": ev.MainText, "detail": ev.DetailText}[args.slot]
            await hud.publish(slot(args.text))
        elif args.cmd == "notify":
            await hud.publish(ev.Notification(args.app, args.title, args.body, ttl_s=args.ttl))
        elif args.cmd == "clear":
            await hud.publish(ev.Clear())
        elif args.cmd == "config":
            hud.link.submit(p.config(flip_h=args.flip_h, flip_v=args.flip_v, invert=args.invert,
                                     offset_x=args.offset_x, offset_y=args.offset_y,
                                     contrast=args.contrast, sleep_s=args.sleep))
        elif args.cmd == "ping":
            await hud.link.flush()
            rtts = []
            for _ in range(args.count):
                rtts.append(await hud.link.ping())
                await asyncio.sleep(0.2)
            rtts.sort()
            print(f"round trip: min {rtts[0]:.1f} ms, median {rtts[len(rtts)//2]:.1f} ms, "
                  f"max {rtts[-1]:.1f} ms  (one-way is roughly half)")
            if hud.link.status:
                s = hud.link.status
                print(f"glasses: fw v{s.fw_version}, battery "
                      f"{'n/a' if s.battery_pct is None else str(s.battery_pct) + '%'}, "
                      f"panel {'on' if s.panel_on else 'off'}")
        await hud.link.flush()
    if ticker:
        ticker.cancel()
    if rec and rec.out_dir:
        print(f"simulator: {rec.n} frames written to {rec.out_dir}/")


def main(argv=None) -> None:
    ap = argparse.ArgumentParser(prog="openhud", description="Open-HUD host tools")
    ap.add_argument("-v", "--verbose", action="store_true")
    sub = ap.add_subparsers(dest="cmd", required=True)

    def common(sp):
        g = sp.add_mutually_exclusive_group()
        g.add_argument("--sim", action="store_true", default=True, help="use the simulator (default)")
        g.add_argument("--ble", action="store_true", help="talk to real glasses over Bluetooth")
        sp.add_argument("--address", help="BLE address (skip scanning)")
        sp.add_argument("--out", help="simulator: folder for PNG frames (default sim_frames)")
        return sp

    d = common(sub.add_parser("demo", help="scripted walk-through: nav, notifications, AI"))
    d.add_argument("--realtime", action="store_true", help="simulator: run at real speed")
    t = common(sub.add_parser("text", help="show text"))
    t.add_argument("text")
    t.add_argument("--slot", choices=["main", "detail"], default="main")
    n = common(sub.add_parser("notify", help="show a notification"))
    n.add_argument("title")
    n.add_argument("body", nargs="?", default="")
    n.add_argument("--app", default="message")
    n.add_argument("--ttl", type=int, default=6)
    common(sub.add_parser("clear", help="blank the display"))
    c = common(sub.add_parser("config", help="optics: flip / offset / contrast / sleep"))
    c.add_argument("--flip-h", action="store_true", help="mirror left-right (most combiners)")
    c.add_argument("--flip-v", action="store_true", help="mirror top-bottom")
    c.add_argument("--invert", action="store_true")
    c.add_argument("--offset-x", type=int, default=0)
    c.add_argument("--offset-y", type=int, default=0)
    c.add_argument("--contrast", type=int, default=200)
    c.add_argument("--sleep", type=int, default=60, help="panel off after N idle seconds (0=never)")
    pg = common(sub.add_parser("ping", help="measure latency"))
    pg.add_argument("--count", type=int, default=10)

    args = ap.parse_args(argv)
    if args.ble:
        args.sim = False
    logging.basicConfig(level=logging.INFO if args.verbose else logging.WARNING,
                        format="%(asctime)s %(name)s: %(message)s")
    t0 = time.perf_counter()
    asyncio.run(amain(args))
    if args.verbose:
        print(f"done in {time.perf_counter() - t0:.1f}s")
