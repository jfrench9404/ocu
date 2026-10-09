from openhud import events as ev
from openhud import protocol as p
from openhud.preprocess import (LlmTicker, Preprocessor, fit, fold, maneuver_to_arrow,
                                round_distance, shorten_street)


def test_fold_to_ascii():
    assert fold("Café “déjà vu” — ok… 🎉") == 'Cafe "deja vu" - ok...'
    assert fold("  lots   of\nspace ") == "lots of space"


def test_fit_truncates_on_word():
    assert fit("Running five minutes late", 12) == "Running.."
    assert fit("short", 12) == "short"
    assert len(fit("x" * 100, 21)) == 21


def test_maneuvers():
    assert maneuver_to_arrow("turn left") == p.ARROW_LEFT
    assert maneuver_to_arrow("Slight Right") == p.ARROW_SLIGHT_RIGHT
    assert maneuver_to_arrow("sharp_left") == p.ARROW_SHARP_LEFT
    assert maneuver_to_arrow("arrive") == p.ARROW_ARRIVE
    assert maneuver_to_arrow("whatever") == p.ARROW_STRAIGHT


def test_street_and_distance():
    assert shorten_street("West Grand Boulevard") == "W Grand Blvd"
    assert round_distance(47) == 45
    assert round_distance(347) == 350
    assert round_distance(1349) == 1300
    assert round_distance(None) is None


def test_event_to_messages():
    pre = Preprocessor()
    [m] = pre.to_messages(ev.Notification("sms", "Sam", "On my way"))
    assert m.type == p.MSG_NOTIFY and m.payload[0] == p.APP_MESSAGE
    msgs = pre.to_messages(ev.StatusText(left="12:30", right="80%"))
    assert [m.key for m in msgs] == [(p.MSG_TEXT, 0), (p.MSG_TEXT, 1)]


def test_llm_ticker_rate_limits_and_flushes():
    t = LlmTicker(min_interval_s=1.0)
    assert t.feed(ev.LlmChunk("Hello "), now=10.0) is not None
    assert t.feed(ev.LlmChunk("there "), now=10.1) is None       # rate-limited
    m = t.feed(ev.LlmChunk("friend", done=True), now=10.2)        # done always flushes
    assert b"Hello there friend" in m.payload
    long = LlmTicker(min_interval_s=0)
    m = long.feed(ev.LlmChunk("word " * 40, done=True), now=0)
    assert len(m.encode(0)) <= p.MAX_FRAME
