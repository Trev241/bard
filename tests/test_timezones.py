import parsedatetime as pdt

from bot.core.message_features import TimezoneResponder
from bot.core.timezones import resolve_timezone


def make_responder():
    return TimezoneResponder(calendar=pdt.Calendar())


def test_resolve_timezone_accepts_iana_name():
    tz = resolve_timezone("America/New_York")

    assert tz is not None
    assert tz.key == "America/New_York"


def test_resolve_timezone_accepts_common_alias():
    tz = resolve_timezone("EST")

    assert tz is not None
    assert tz.key == "America/New_York"


def test_parse_time_reference_accepts_clock_time():
    responder = make_responder()
    tz = resolve_timezone("America/New_York")

    timestamp = responder.parse_time_reference("4:00 PM", tz)

    assert timestamp is not None
    assert timestamp.hour == 16
    assert timestamp.minute == 0


def test_parse_time_reference_accepts_relative_time():
    responder = make_responder()
    tz = resolve_timezone("America/New_York")

    timestamp = responder.parse_time_reference("2 hours from now", tz)

    assert timestamp is not None
    assert timestamp.tzinfo is tz


def test_timezone_gate_accepts_meeting_relative_time():
    assert TimezoneResponder.should_attempt_timezone_conversion("meeting in 2 hours") is True


def test_timezone_gate_accepts_clock_time_without_trigger_word():
    assert TimezoneResponder.should_attempt_timezone_conversion("4:00 PM") is True


def test_timezone_gate_rejects_completed_duration():
    assert (
        TimezoneResponder.should_attempt_timezone_conversion(
            "the test was completed in 2 hours"
        )
        is False
    )


def test_timezone_gate_rejects_took_duration():
    assert TimezoneResponder.should_attempt_timezone_conversion("it took 4 hours") is False


def test_parse_time_reference_rejects_completed_duration():
    responder = make_responder()
    tz = resolve_timezone("America/New_York")

    timestamp = responder.parse_time_reference("the test was completed in 2 hours", tz)

    assert timestamp is None
