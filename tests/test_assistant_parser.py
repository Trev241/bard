from bot.core.assistant.llm import OpenRouterIntentParser
from bot.core.assistant.models import AssistantAction
from bot.core.assistant.parsing import RuleBasedIntentParser


def parse(text):
    return RuleBasedIntentParser().parse(text)


def test_parser_extracts_play_query_from_natural_language():
    intent = parse("Bard, can you play Daft Punk One More Time please?")

    assert intent.action == AssistantAction.PLAY
    assert intent.query == "Daft Punk One More Time"
    assert intent.confidence >= 0.9


def test_parser_handles_direct_play_command():
    intent = parse("put on some jazz")

    assert intent.action == AssistantAction.PLAY
    assert intent.query == "some jazz"


def test_parser_handles_play_request_without_bard_prefix():
    intent = parse("can we hear music from Interstellar")

    assert intent.action == AssistantAction.PLAY
    assert intent.query == "music from Interstellar"


def test_parser_handles_playback_controls():
    cases = {
        "pause the song": AssistantAction.PAUSE,
        "resume playing": AssistantAction.RESUME,
        "skip this track": AssistantAction.SKIP,
        "ok bard disconnect": AssistantAction.DISCONNECT,
        "what song is this": AssistantAction.NOW,
        "loop this song": AssistantAction.LOOP,
        "loop the queue": AssistantAction.LOOP_QUEUE,
    }

    for text, action in cases.items():
        assert parse(text).action == action


def test_parser_returns_unknown_for_vague_requests():
    intent = parse("I am tired of this one")

    assert intent.action == AssistantAction.UNKNOWN


def test_openrouter_parser_normalizes_valid_json():
    intent = OpenRouterIntentParser.intent_from_data(
        "play something",
        {"action": "play", "query": "lofi", "confidence": 0.82},
    )

    assert intent.action == AssistantAction.PLAY
    assert intent.query == "lofi"
    assert intent.confidence == 0.82
    assert intent.source == "openrouter"


def test_openrouter_parser_rejects_play_without_query():
    intent = OpenRouterIntentParser.intent_from_data(
        "play something",
        {"action": "play", "query": "", "confidence": 0.82},
    )

    assert intent.action == AssistantAction.UNKNOWN
    assert intent.confidence == 0.0
