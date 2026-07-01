from bot.core.translation_settings import (
    GuildTranslationSettings,
    TranslationSettingsStore,
    direction_key,
)


def test_translation_settings_store_round_trips_guild_settings(tmp_path):
    path = tmp_path / "settings.json"
    store = TranslationSettingsStore(path)
    setting = GuildTranslationSettings(
        guild_id=123,
        source_channel_id=111,
        mirror_channel_id=222,
        providers={
            direction_key("en", "fr"): "gemini",
            direction_key("fr", "en"): "argos",
        },
        auto_rewrite_enabled=True,
        auto_rewrite_threshold=32,
        llm_extra_instructions="Prefer casual corrections.",
    )

    store.save(setting)

    loaded = store.get(123)
    assert loaded.source_channel_id == 111
    assert loaded.mirror_channel_id == 222
    assert loaded.provider_for("en", "fr") == "gemini"
    assert loaded.provider_for("fr", "en") == "argos"
    assert loaded.auto_rewrite_enabled is True
    assert loaded.auto_rewrite_threshold == 32
    assert loaded.llm_extra_instructions == "Prefer casual corrections."


def test_translation_settings_store_returns_default_for_missing_guild(tmp_path):
    store = TranslationSettingsStore(tmp_path / "settings.json")

    setting = store.get(999)

    assert setting.guild_id == 999
    assert setting.configured is False
    assert setting.source_lang == "en"
    assert setting.mirror_lang == "fr"
