import pytest

from bot import config
from bot.cogs.translation import TranslationChannelPair
from bot.core.translation import (
    LanguagePair,
    TranslationCache,
    TranslationError,
    TranslationProvider,
    TranslationRequest,
    TranslationResult,
    TranslationService,
)


class FakeTranslationProvider(TranslationProvider):
    name = "fake"

    def __init__(self):
        self.calls = 0

    def supports(self, pair):
        return pair == LanguagePair("en", "fr")

    def translate_sync(self, request):
        self.calls += 1
        return TranslationResult(
            translated_text=f"translated:{request.text}",
            provider=self.name,
            source_text=request.text,
            pair=request.pair,
        )


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
