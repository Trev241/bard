import parsedatetime as pdt

from bot.cogs.events import Events
from bot.core.timezones import resolve_timezone


def make_events():
    events = Events.__new__(Events)
    events.calendar = pdt.Calendar()
    return events


def test_resolve_timezone_accepts_iana_name():
    tz = resolve_timezone("America/New_York")

    assert tz is not None
    assert tz.key == "America/New_York"


def test_resolve_timezone_accepts_common_alias():
    tz = resolve_timezone("EST")

    assert tz is not None
    assert tz.key == "America/New_York"


def test_parse_time_reference_accepts_clock_time():
    events = make_events()
    tz = resolve_timezone("America/New_York")

    timestamp = events.parse_time_reference("4:00 PM", tz)

    assert timestamp is not None
    assert timestamp.hour == 16
    assert timestamp.minute == 0


def test_parse_time_reference_accepts_relative_time():
    events = make_events()
    tz = resolve_timezone("America/New_York")

    timestamp = events.parse_time_reference("2 hours from now", tz)

    assert timestamp is not None
    assert timestamp.tzinfo is tz


def test_timezone_gate_accepts_meeting_relative_time():
    assert Events.should_attempt_timezone_conversion("meeting in 2 hours") is True


def test_timezone_gate_accepts_clock_time_without_trigger_word():
    assert Events.should_attempt_timezone_conversion("4:00 PM") is True


def test_timezone_gate_rejects_completed_duration():
    assert (
        Events.should_attempt_timezone_conversion(
            "the test was completed in 2 hours"
        )
        is False
    )


def test_timezone_gate_rejects_took_duration():
    assert Events.should_attempt_timezone_conversion("it took 4 hours") is False


def test_parse_time_reference_rejects_completed_duration():
    events = make_events()
    tz = resolve_timezone("America/New_York")

    timestamp = events.parse_time_reference("the test was completed in 2 hours", tz)

    assert timestamp is None
