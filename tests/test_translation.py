import pytest

from bot import config
from bot.cogs.translation import TranslationChannelPair
from bot.cogs.translation import Translation
from bot.core.translation import (
    LanguagePair,
    TranslationCache,
    TranslationError,
    TranslationProvider,
    TranslationRequest,
    TranslationResult,
    TranslationService,
)
from bot.core.writing_feedback import WritingFeedbackIssue, WritingFeedbackResult


class FakeTranslationProvider(TranslationProvider):
    name = "fake"

    def __init__(self):
        self.calls = 0
        self.warmups = 0

    def supports(self, pair):
        return pair == LanguagePair("en", "fr")

    def warmup_sync(self):
        self.warmups += 1

    def translate_sync(self, request):
        self.calls += 1
        return TranslationResult(
            translated_text=f"translated:{request.text}",
            provider=self.name,
            source_text=request.text,
            pair=request.pair,
        )


class FakeAuthor:
    def __init__(self, display_name="Trevis", bot=False, avatar_url=None):
        self.display_name = display_name
        self.bot = bot
        self.display_avatar = type("Avatar", (), {"url": avatar_url})()


class FakeMessage:
    def __init__(
        self,
        id=1,
        content="Bonjour",
        author=None,
        channel=None,
        webhook_id=None,
    ):
        self.id = id
        self.content = content
        self.author = author or FakeAuthor()
        self.channel = channel
        self.webhook_id = webhook_id


class FakeWebhook:
    def __init__(self):
        self.name = "Bard Translation Mirror"
        self.sent = []

    async def send(self, content, **kwargs):
        self.sent.append((content, kwargs))
        return FakeMessage(id=500, content=content)


class FakeChannel:
    def __init__(self, id=200):
        self.id = id
        self.webhook = FakeWebhook()
        self.bot_messages = []

    async def webhooks(self):
        return [self.webhook]

    async def create_webhook(self, **kwargs):
        self.webhook = FakeWebhook()
        return self.webhook

    async def send(self, content, **kwargs):
        self.bot_messages.append((content, kwargs))
        return FakeMessage(id=600, content=content)


@pytest.mark.asyncio
async def test_translation_service_uses_provider_and_cache():
    provider = FakeTranslationProvider()
    service = TranslationService(
        [provider],
        cache=TranslationCache(max_size=10),
        max_concurrency=1,
    )
    request = TranslationRequest(" hello   world ", LanguagePair("en", "fr"))

    first = await service.translate(request)
    second = await service.translate(request)

    assert first.translated_text == "translated:hello   world"
    assert second == first
    assert provider.calls == 1


@pytest.mark.asyncio
async def test_translation_service_warms_up_provider():
    provider = FakeTranslationProvider()
    service = TranslationService([provider])

    await service.warmup()

    assert provider.warmups == 1


@pytest.mark.asyncio
async def test_translation_service_rejects_unsupported_pair():
    service = TranslationService([FakeTranslationProvider()])

    with pytest.raises(TranslationError):
        await service.translate(TranslationRequest("bonjour", LanguagePair("fr", "en")))


def test_translation_channel_pair_maps_both_directions():
    pair = TranslationChannelPair(
        source_channel_id=100,
        mirror_channel_id=200,
        source_lang="en",
        mirror_lang="fr",
    )

    assert pair.direction_for(100) == LanguagePair("en", "fr")
    assert pair.direction_for(200) == LanguagePair("fr", "en")
    assert pair.target_channel_id_for(100) == 200
    assert pair.target_channel_id_for(200) == 100
    assert pair.direction_for(300) is None
    assert pair.target_channel_id_for(300) is None


def test_parse_translation_channel_pairs():
    parsed = config.parse_translation_channel_pairs("100:200:en:fr,300:400:fr:en")

    assert parsed == [
        {
            "source_channel_id": 100,
            "mirror_channel_id": 200,
            "source_lang": "en",
            "mirror_lang": "fr",
        },
        {
            "source_channel_id": 300,
            "mirror_channel_id": 400,
            "source_lang": "fr",
            "mirror_lang": "en",
        },
    ]


def test_parse_translation_channel_pairs_rejects_invalid_entry():
    with pytest.raises(ValueError):
        config.parse_translation_channel_pairs("100:200:en")


def test_format_writing_feedback_includes_score_issues_and_recommendation():
    cog = Translation(client=None, service=None, channel_pairs=[])
    message = type(
        "Message",
        (),
        {"author": type("Author", (), {"display_name": "Trevis"})()},
    )()
    result = WritingFeedbackResult(
        score=32,
        language="fr",
        source_text="Je aller au magasin.",
        provider="fake",
        issues=(
            WritingFeedbackIssue(
                start=3,
                end=8,
                message="Conjugaison incorrecte.",
                suggestions=("vais",),
            ),
        ),
        recommendation="Je vais au magasin.",
    )

    formatted = cog._format_writing_feedback(message, result)

    assert "**Trevis** French writing score: 32/100" in formatted
    assert "Conjugaison incorrecte. Suggestion: vais" in formatted
    assert "Recommended: Je vais au magasin." in formatted


def test_format_context_message_caps_content():
    message = FakeMessage(content="mot " * 100)

    formatted = Translation._format_context_message(message)

    assert formatted.startswith("Trevis: mot")
    assert len(formatted) <= 240 + len("Trevis: ")
    assert formatted.endswith("...")


def test_format_webhook_mirror_message_omits_author_header():
    result = TranslationResult(
        translated_text="Bonjour le monde",
        provider="fake",
        source_text="Hello world",
        pair=LanguagePair("en", "fr"),
    )

    assert Translation._format_webhook_mirror_message(result) == "Bonjour le monde"


def test_webhook_username_and_avatar_url():
    message = FakeMessage(
        author=FakeAuthor(
            display_name="  Trevis   Liu  ",
            avatar_url="https://example.com/avatar.png",
        )
    )

    assert Translation._webhook_username(message) == "Trevis Liu"
    assert Translation._webhook_avatar_url(message) == "https://example.com/avatar.png"


@pytest.mark.asyncio
async def test_send_mirrored_message_uses_webhook(monkeypatch):
    monkeypatch.setattr(config, "TRANSLATION_USE_WEBHOOKS", True)
    cog = Translation(client=None, service=None, channel_pairs=[])
    channel = FakeChannel()
    source_message = FakeMessage(
        author=FakeAuthor(display_name="Trevis", avatar_url="https://example.com/a.png")
    )
    result = TranslationResult(
        translated_text="Bonjour",
        provider="fake",
        source_text="Hello",
        pair=LanguagePair("en", "fr"),
    )

    mirrored = await cog._send_mirrored_message(channel, source_message, result)

    assert mirrored.id == 500
    assert channel.webhook.sent[0][0] == "Bonjour"
    assert channel.webhook.sent[0][1]["username"] == "Trevis"
    assert channel.webhook.sent[0][1]["avatar_url"] == "https://example.com/a.png"
    assert channel.bot_messages == []


def test_should_use_context_message_skips_bots_and_mirrors():
    cog = Translation(client=None, service=None, channel_pairs=[])
    current = FakeMessage(id=10)
    bot_message = FakeMessage(id=11, author=FakeAuthor(bot=True))
    mirrored_message = FakeMessage(id=12)
    cog.registry.by_source_message_id[mirrored_message.id] = object()

    assert not cog._should_use_context_message(bot_message, current_message=current)
    assert not cog._should_use_context_message(
        mirrored_message,
        current_message=current,
    )
    assert cog._should_use_context_message(
        FakeMessage(id=13, content="Tu viens ?"),
        current_message=current,
    )


def test_feedback_language_for_accepts_human_mirror_channel_message(monkeypatch):
    monkeypatch.setattr(config, "WRITING_FEEDBACK_LANGUAGES", {"fr"})
    pair = TranslationChannelPair(
        source_channel_id=100,
        mirror_channel_id=200,
        source_lang="en",
        mirror_lang="fr",
    )
    cog = Translation(client=None, service=None, channel_pairs=[pair])
    message = FakeMessage(channel=FakeChannel(id=200), content="Bonjour")

    assert cog._feedback_language_for(message) == "fr"


def test_feedback_language_for_rejects_source_webhook_and_bot_messages(monkeypatch):
    monkeypatch.setattr(config, "WRITING_FEEDBACK_LANGUAGES", {"fr"})
    pair = TranslationChannelPair(
        source_channel_id=100,
        mirror_channel_id=200,
        source_lang="en",
        mirror_lang="fr",
    )
    cog = Translation(client=None, service=None, channel_pairs=[pair])

    assert cog._feedback_language_for(
        FakeMessage(channel=FakeChannel(id=100), content="Hello")
    ) is None
    assert cog._feedback_language_for(
        FakeMessage(channel=FakeChannel(id=200), webhook_id=123)
    ) is None
    assert cog._feedback_language_for(
        FakeMessage(channel=FakeChannel(id=200), author=FakeAuthor(bot=True))
    ) is None
