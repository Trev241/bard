import asyncio
import builtins

import pytest
import requests

from bot import config
from bot.cogs.translation import TranslationChannelPair
from bot.cogs.translation import Translation
from bot.core.translation import (
    CasualEnglishNormalizer,
    GeminiTranslateProvider,
    LanguagePair,
    ArgosTranslateProvider,
    SlangAwareTranslationProvider,
    TranslationCache,
    TranslationError,
    TranslationProviderRouter,
    TranslationProvider,
    TranslationRequest,
    TranslationResult,
    TranslationService,
    SQLiteTranslationCache,
)
from bot.core.writing_feedback import WritingFeedbackIssue, WritingFeedbackResult
from bot.core.translation_settings import GuildTranslationSettings


class FakeTranslationProvider(TranslationProvider):
    name = "fake"

    def __init__(self):
        self.calls = 0
        self.warmups = 0
        self.requests = []

    def supports(self, pair):
        return pair == LanguagePair("en", "fr")

    def warmup_sync(self):
        self.warmups += 1

    def translate_sync(self, request):
        self.calls += 1
        self.requests.append(request)
        return TranslationResult(
            translated_text=f"translated:{request.text}",
            provider=self.name,
            source_text=request.text,
            pair=request.pair,
        )


class FakeHTTPSession:
    def __init__(self, post):
        self.post = post


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
        jump_url="https://discord.com/channels/1/2/3",
    ):
        self.id = id
        self.content = content
        self.author = author or FakeAuthor()
        self.channel = channel
        self.webhook_id = webhook_id
        self.jump_url = jump_url


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


class FakeClient:
    def __init__(self, channels=None):
        self.channels = channels or {}

    def get_channel(self, channel_id):
        return self.channels.get(channel_id)

    async def fetch_channel(self, channel_id):
        return self.channels.get(channel_id)


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
async def test_translation_service_cache_is_scoped_by_guild():
    provider = FakeTranslationProvider()
    service = TranslationService(
        [provider],
        cache=TranslationCache(max_size=10),
        max_concurrency=1,
    )
    pair = LanguagePair("en", "fr")

    first = await service.translate(
        TranslationRequest("hello", pair, context={"guild_id": 1})
    )
    second = await service.translate(
        TranslationRequest("hello", pair, context={"guild_id": 2})
    )
    third = await service.translate(
        TranslationRequest("hello", pair, context={"guild_id": 1})
    )

    assert first == third
    assert second.translated_text == "translated:hello"
    assert provider.calls == 2


@pytest.mark.asyncio
async def test_sqlite_translation_cache_persists_between_instances(tmp_path):
    cache_path = tmp_path / "translation-cache.sqlite3"
    provider = FakeTranslationProvider()
    pair = LanguagePair("en", "fr")
    request = TranslationRequest("hello", pair, context={"guild_id": 1})
    first_service = TranslationService(
        [provider],
        cache=SQLiteTranslationCache(cache_path, max_size=10),
    )

    first = await first_service.translate(request)
    second_service = TranslationService(
        [provider],
        cache=SQLiteTranslationCache(cache_path, max_size=10),
    )
    second = await second_service.translate(request)

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


@pytest.mark.asyncio
async def test_translation_service_normalizes_casual_english_before_provider():
    provider = FakeTranslationProvider()
    service = TranslationService(
        [SlangAwareTranslationProvider(provider)],
        cache=TranslationCache(max_size=0),
    )

    result = await service.translate(
        TranslationRequest("ur using an llm", LanguagePair("en", "fr"))
    )

    assert provider.requests[0].text == "you are using a large language model"
    assert result.translated_text == "translated:you are using a large language model"
    assert result.source_text == "ur using an llm"
    assert result.notes == ("Normalized casual English before translation.",)


@pytest.mark.asyncio
async def test_translation_service_normalizes_slang_phrases_before_provider():
    provider = FakeTranslationProvider()
    service = TranslationService(
        [SlangAwareTranslationProvider(provider)],
        cache=TranslationCache(max_size=0),
    )

    first = await service.translate(
        TranslationRequest("don't bs me", LanguagePair("en", "fr"))
    )
    second = await service.translate(TranslationRequest("vas", LanguagePair("en", "fr")))

    assert provider.requests[0].text == "do not bullshit me"
    assert first.translated_text == "translated:do not bullshit me"
    assert provider.requests[1].text == "what's up"
    assert second.translated_text == "translated:what's up"


def test_casual_english_normalizer_loads_rules_from_file(tmp_path):
    rules_path = tmp_path / "normalization.en.json"
    rules_path.write_text(
        """
        {
          "version": 1,
          "source_language": "en",
          "rules": [
            {
              "pattern": "\\\\bomw\\\\b",
              "replacement": "on my way"
            }
          ]
        }
        """,
        encoding="utf-8",
    )
    normalizer = CasualEnglishNormalizer(rules_path)

    result = normalizer.normalize(
        TranslationRequest("omw", LanguagePair("en", "fr"))
    )

    assert result.text == "on my way"


def test_gemini_translate_provider_extracts_translated_text():
    payload = {
        "candidates": [
            {
                "content": {
                    "parts": [
                        {"text": '{"translated_text":"Bonjour le monde"}'},
                    ],
                }
            }
        ]
    }

    assert (
        GeminiTranslateProvider.translated_text_from_payload(payload)
        == "Bonjour le monde"
    )


def test_gemini_translate_provider_tries_next_model_after_http_error(monkeypatch):
    failed_response = requests.Response()
    failed_response.status_code = 400
    failed_response.url = GeminiTranslateProvider.endpoint_for_model("model-one")

    ok_response = requests.Response()
    ok_response.status_code = 200
    ok_response._content = (
        b'{"candidates":[{"content":{"parts":[{"text":'
        b'"{\\"translated_text\\":\\"Bonjour\\"}"}]}}]}'
    )
    seen_models = []

    def fake_post(*args, **kwargs):
        url = args[0]
        model = url.rsplit("/models/", 1)[1].split(":", 1)[0]
        seen_models.append(model)
        if model == "model-one":
            return failed_response
        return ok_response

    provider = GeminiTranslateProvider(
        [LanguagePair("en", "fr")],
        api_key="key",
        model="model-one,model-two",
        session=FakeHTTPSession(fake_post),
    )

    result = provider.translate_sync(
        TranslationRequest("hello", LanguagePair("en", "fr"))
    )

    assert result.translated_text == "Bonjour"
    assert seen_models == ["model-one", "model-two"]


def test_gemini_translate_provider_translates_batch_in_one_request():
    ok_response = requests.Response()
    ok_response.status_code = 200
    ok_response._content = (
        b'{"candidates":[{"content":{"parts":[{"text":'
        b'"{\\"translations\\":[{\\"id\\":\\"0\\",\\"translated_text\\":\\"Bonjour\\"},'
        b'{\\"id\\":\\"1\\",\\"translated_text\\":\\"Au revoir\\"}]}"}]}}]}'
    )
    calls = []

    def fake_post(*args, **kwargs):
        calls.append(kwargs["json"])
        return ok_response

    provider = GeminiTranslateProvider(
        [LanguagePair("en", "fr")],
        api_key="key",
        model="gemini-test",
        session=FakeHTTPSession(fake_post),
    )

    results = provider.translate_many_sync(
        (
            TranslationRequest("hello", LanguagePair("en", "fr")),
            TranslationRequest("bye", LanguagePair("en", "fr")),
        )
    )

    assert [result.translated_text for result in results] == ["Bonjour", "Au revoir"]
    assert len(calls) == 1


def test_gemini_translate_provider_enters_cooldown_after_rate_limit():
    response = requests.Response()
    response.status_code = 429
    response.url = GeminiTranslateProvider.endpoint_for_model("gemini-test")
    response.headers["Retry-After"] = "12"
    calls = 0

    def fake_post(*args, **kwargs):
        nonlocal calls
        calls += 1
        return response

    provider = GeminiTranslateProvider(
        [LanguagePair("en", "fr")],
        api_key="key",
        model="gemini-test",
        rate_limit_cooldown_seconds=60,
        session=FakeHTTPSession(fake_post),
    )

    with pytest.raises(TranslationError):
        provider.translate_sync(TranslationRequest("hello", LanguagePair("en", "fr")))
    with pytest.raises(TranslationError, match="cooldown"):
        provider.translate_sync(TranslationRequest("hello", LanguagePair("en", "fr")))

    assert calls == 1
    assert provider._cooldown_until > 0


def test_argos_warmup_does_not_require_argostranslate(monkeypatch):
    real_import = builtins.__import__

    def fake_import(name, *args, **kwargs):
        if name.startswith("argostranslate"):
            raise ImportError("missing argos")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", fake_import)
    provider = ArgosTranslateProvider([LanguagePair("en", "fr")])

    provider.warmup_sync()


def test_translation_provider_router_selects_provider_by_direction():
    class DirectionProvider(FakeTranslationProvider):
        def __init__(self, source, target, name):
            super().__init__()
            self.pair = LanguagePair(source, target)
            self.name = name

        def supports(self, pair):
            return pair == self.pair

    en_fr = DirectionProvider("en", "fr", "en-fr")
    fr_en = DirectionProvider("fr", "en", "fr-en")
    router = TranslationProviderRouter([en_fr, fr_en])

    first = router.translate_sync(TranslationRequest("hello", LanguagePair("en", "fr")))
    second = router.translate_sync(
        TranslationRequest("bonjour", LanguagePair("fr", "en"))
    )

    assert first.provider == "en-fr"
    assert second.provider == "fr-en"


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


def test_format_writing_feedback_with_notes_uses_inline_rewrite_layout():
    cog = Translation(client=None, service=None, channel_pairs=[])
    message = type(
        "Message",
        (),
        {
            "author": type("Author", (), {"display_name": "Trevis"})(),
            "content": "Je aller.",
        },
    )()
    result = WritingFeedbackResult(
        score=32,
        language="fr",
        source_text="Je aller.",
        provider="fake",
        recommendation="Je vais.",
        rewrite_notes=("Use je vais to conjugate aller in the present tense.",),
        llm_rewrite=True,
    )

    formatted = cog._format_writing_feedback(message, result)

    assert "**French rewrite**" not in formatted
    assert "**Trevis** French rewrite" not in formatted
    assert "Original:\nJe aller." in formatted
    assert "Natural rewrite:\nJe vais." in formatted
    assert "- Use je vais to conjugate aller in the present tense." in formatted


def test_format_writing_feedback_uses_rewrite_layout_without_notes():
    cog = Translation(client=None, service=None, channel_pairs=[])
    message = type(
        "Message",
        (),
        {"author": type("Author", (), {"display_name": "Trevis"})()},
    )()
    result = WritingFeedbackResult(
        score=100,
        language="fr",
        source_text="Bonjour.",
        provider="fake",
        recommendation="Salut.",
        rewrite_notes=(),
        llm_rewrite=True,
    )

    formatted = cog._format_writing_feedback(message, result)

    assert "**French rewrite**" not in formatted
    assert "**Trevis** French rewrite" not in formatted
    assert "Natural rewrite:\nSalut." in formatted


def test_format_context_message_caps_content():
    message = FakeMessage(content="mot " * 100)

    formatted = Translation._format_context_message(message)

    assert formatted.startswith("Trevis: mot")
    assert len(formatted) <= 240 + len("Trevis: ")
    assert formatted.endswith("...")


def test_format_webhook_mirror_message_adds_source_subtext_link():
    message = FakeMessage(jump_url="https://discord.com/channels/1/2/3")
    result = TranslationResult(
        translated_text="Bonjour le monde",
        provider="fake",
        source_text="Hello world",
        pair=LanguagePair("en", "fr"),
    )

    assert (
        Translation._format_webhook_mirror_message(message, result)
        == "Bonjour le monde\n-# [View original](https://discord.com/channels/1/2/3)"
    )


def test_format_webhook_mirror_message_keeps_translation_text_plain():
    message = FakeMessage(jump_url="https://discord.com/channels/1/2/3")
    result = TranslationResult(
        translated_text="Bonjour [ami]",
        provider="fake",
        source_text="Hello [friend]",
        pair=LanguagePair("en", "fr"),
    )

    assert (
        Translation._format_webhook_mirror_message(message, result)
        == "Bonjour [ami]\n-# [View original](https://discord.com/channels/1/2/3)"
    )


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
    assert (
        channel.webhook.sent[0][0]
        == "Bonjour\n-# [View original](https://discord.com/channels/1/2/3)"
    )
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


def test_automatic_writing_feedback_enabled_uses_guild_settings():
    pair = TranslationChannelPair(
        source_channel_id=100,
        mirror_channel_id=200,
        source_lang="en",
        mirror_lang="fr",
        guild_id=1,
    )
    cog = Translation(
        client=None,
        service=None,
        channel_pairs=[pair],
        guild_settings={
            1: GuildTranslationSettings(guild_id=1, auto_rewrite_enabled=True)
        },
    )

    assert cog._automatic_writing_feedback_enabled(pair)


def test_automatic_writing_feedback_disabled_without_guild_settings():
    pair = TranslationChannelPair(
        source_channel_id=100,
        mirror_channel_id=200,
        source_lang="en",
        mirror_lang="fr",
    )
    cog = Translation(client=None, service=None, channel_pairs=[pair])

    assert not cog._automatic_writing_feedback_enabled(pair)


def test_translation_batching_enabled_only_for_gemini_direction(monkeypatch):
    monkeypatch.setattr(config, "TRANSLATION_GEMINI_BATCH_ENABLED", True)
    pair = TranslationChannelPair(
        source_channel_id=100,
        mirror_channel_id=200,
        source_lang="en",
        mirror_lang="fr",
        guild_id=1,
    )
    settings = GuildTranslationSettings(
        guild_id=1,
        providers={
            "en->fr": "gemini",
            "fr->en": "argos",
        },
    )
    cog = Translation(
        client=None,
        service=None,
        channel_pairs=[pair],
        guild_settings={1: settings},
    )

    assert cog._translation_batching_enabled(pair, LanguagePair("en", "fr"))
    assert not cog._translation_batching_enabled(pair, LanguagePair("fr", "en"))


def test_low_value_translation_message_detection():
    assert Translation._is_low_value_translation_message("😂😂")
    assert Translation._is_low_value_translation_message("https://example.com")
    assert Translation._is_low_value_translation_message("<:wave:1234567890>")
    assert Translation._is_low_value_translation_message("!!!")
    assert not Translation._is_low_value_translation_message("hello 😂")


def test_should_ignore_allows_low_value_messages_for_passthrough(monkeypatch):
    monkeypatch.setattr(config, "TRANSLATION_SKIP_LOW_VALUE_MESSAGES", True)
    cog = Translation(client=None, service=None, channel_pairs=[])

    assert not cog._should_ignore(FakeMessage(content="https://example.com"))


def test_passthrough_translation_result_keeps_original_content():
    message = FakeMessage(content="https://example.com")
    pair = LanguagePair("en", "fr")

    result = Translation._passthrough_translation_result(message, pair)

    assert result.translated_text == "https://example.com"
    assert result.source_text == "https://example.com"
    assert result.provider == "passthrough"
    assert result.pair == pair


@pytest.mark.asyncio
async def test_rate_limit_notice_is_sent_once_per_cooldown(monkeypatch):
    monkeypatch.setattr(config, "TRANSLATION_GEMINI_RATE_LIMIT_COOLDOWN_SECONDS", 60)
    channel = FakeChannel(id=200)
    cog = Translation(
        client=FakeClient({200: channel}),
        service=None,
        channel_pairs=[],
    )

    await cog._send_rate_limit_notice(200)
    await cog._send_rate_limit_notice(200)

    assert len(channel.bot_messages) == 1
    assert "rate-limited" in channel.bot_messages[0][0]


@pytest.mark.asyncio
async def test_schedule_writing_feedback_tracks_background_task(monkeypatch):
    pair = TranslationChannelPair(
        source_channel_id=100,
        mirror_channel_id=200,
        source_lang="en",
        mirror_lang="fr",
    )
    cog = Translation(client=None, service=None, channel_pairs=[pair])
    started = asyncio.Event()
    release = asyncio.Event()

    async def fake_send_writing_feedback(*args):
        started.set()
        await release.wait()

    monkeypatch.setattr(cog, "_send_writing_feedback", fake_send_writing_feedback)

    cog._schedule_writing_feedback(
        FakeMessage(channel=FakeChannel(id=200)),
        pair,
        LanguagePair("fr", "en"),
    )
    await started.wait()

    assert len(cog._background_tasks) == 1
    task = next(iter(cog._background_tasks))

    release.set()
    await task

    assert len(cog._background_tasks) == 0


@pytest.mark.asyncio
async def test_translation_cog_reload_settings_rebuilds_runtime_state(monkeypatch):
    initial_pair = TranslationChannelPair(
        source_channel_id=100,
        mirror_channel_id=200,
        source_lang="en",
        mirror_lang="fr",
        guild_id=1,
    )
    reloaded_pair = TranslationChannelPair(
        source_channel_id=300,
        mirror_channel_id=400,
        source_lang="en",
        mirror_lang="fr",
        guild_id=1,
    )
    settings = {1: GuildTranslationSettings(guild_id=1)}
    service = TranslationService([FakeTranslationProvider()])
    new_service = TranslationService([FakeTranslationProvider()])
    cog = Translation(
        client=type("Client", (), {"guilds": []})(),
        service=service,
        channel_pairs=[initial_pair],
        guild_settings=settings,
    )

    monkeypatch.setattr(
        "bot.cogs.translation.load_guild_translation_settings",
        lambda guilds: settings,
    )
    monkeypatch.setattr(
        "bot.cogs.translation.channel_pairs_from_guild_settings",
        lambda loaded_settings: [reloaded_pair],
    )
    monkeypatch.setattr(
        "bot.cogs.translation.build_translation_service",
        lambda pairs, loaded_settings: new_service,
    )
    monkeypatch.setattr(
        "bot.cogs.translation.build_writing_feedback_service",
        lambda: None,
    )

    await cog.reload_settings()

    assert cog.service is new_service
    assert cog.channel_pairs == [reloaded_pair]
    assert (300, 400) in cog._locks
    assert (100, 200) not in cog._locks
