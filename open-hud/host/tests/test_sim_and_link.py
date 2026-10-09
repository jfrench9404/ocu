import asyncio

from openhud import events as ev
from openhud import protocol as p
from openhud.hud import Hud
from openhud.link import HudLink
from openhud.sim import SimDevice, render
from openhud.transport import SimTransport


def test_device_applies_frames():
    d = SimDevice(clock=lambda: 0.0)
    assert d.apply(p.text(p.SLOT_DETAIL, "hi").encode(1)) == 0
    assert d.state.slots[p.SLOT_DETAIL] == "hi"
    assert d.apply(p.nav(p.ARROW_LEFT, 200, "Main").encode(2)) == 0
    assert d.state.nav_active and d.state.nav_distance_m == 200
    assert d.apply(p.nav_end().encode(3)) == 0 and not d.state.nav_active
    assert d.apply(bytes([0x7E, 0, 0])) == p.ERR_UNKNOWN_TYPE
    assert d.apply(bytes([p.MSG_TEXT, 0, 2, 9, 65])) == p.ERR_BAD_SLOT
    assert d.apply(bytes([p.MSG_TEXT, 0, 5, 1])) == p.ERR_BAD_LENGTH


def test_notification_expires():
    now = [0.0]
    d = SimDevice(clock=lambda: now[0])
    d.apply(p.notify(p.APP_MESSAGE, "A", "b", ttl_s=3).encode(0))
    now[0] = 2.9
    d.tick()
    assert d.state.notif_active
    now[0] = 3.0
    d.tick()
    assert not d.state.notif_active


def test_flip_h_mirrors_frame():
    d = SimDevice()
    d.apply(p.text(p.SLOT_STATUS_L, "L").encode(0))
    normal = render(d.state)
    d.apply(p.config(flip_h=True).encode(0))
    flipped = render(d.state)
    assert normal.transpose(0).tobytes() == flipped.tobytes()  # 0 = FLIP_LEFT_RIGHT


def test_render_is_pure_black_when_empty():
    d = SimDevice()
    d.apply(p.clear().encode(0))
    assert render(d.state).getbbox() is None


async def _run_link_scenario():
    dev = SimDevice()
    tr = SimTransport(dev)
    link = HudLink(tr)
    await link.start()
    await asyncio.wait_for(link.connected_event.wait(), 1)

    # Latest wins: many MAIN updates queued at once -> only the last one matters.
    for i in range(50):
        link.submit(p.text(p.SLOT_MAIN, f"n{i}"))
    await link.flush()
    assert dev.state.slots[p.SLOT_MAIN] == "n49"
    assert dev.frames_received < 10

    rtt = await link.ping()
    assert rtt >= 0 and link.status is not None

    # Simulate a reboot + range drop: state must be replayed on reconnect.
    link.submit(p.config(flip_h=True))
    link.submit(p.nav(p.ARROW_RIGHT, 100, "Elm"))
    await link.flush()
    await tr.drop()
    dev.__init__()  # glasses rebooted: blank state
    await asyncio.wait_for(link.connected_event.wait(), 2)
    await link.flush()
    assert dev.state.cfg.flags & p.CFG_FLIP_H
    assert dev.state.nav_active and dev.state.slots[p.SLOT_MAIN] == "n49"
    await link.stop()


def test_link_coalesces_and_recovers():
    asyncio.run(_run_link_scenario())


async def _run_hud():
    dev = SimDevice()
    async with Hud(SimTransport(dev)) as hud:
        await hud.link.connected_event.wait()
        await hud.publish(ev.NavUpdate("turn left", 347, "North Main Street"))
        await hud.link.flush()
    assert dev.state.nav_arrow == p.ARROW_LEFT
    assert dev.state.nav_distance_m == 350
    assert dev.state.nav_text == "N Main St"


def test_hud_end_to_end():
    asyncio.run(_run_hud())
