from bot.core.translation_settings import (
    GlobalTranslationSettings,
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
    assert loaded.configured is True


def test_translation_settings_store_returns_default_for_missing_guild(tmp_path):
    store = TranslationSettingsStore(tmp_path / "settings.json")

    setting = store.get(999)

    assert setting.guild_id == 999
    assert setting.configured is False
    assert setting.source_lang == "en"
    assert setting.mirror_lang == "fr"


def test_translation_settings_store_loads_global_defaults_when_missing(tmp_path):
    store = TranslationSettingsStore(
        tmp_path / "settings.json",
        default_batch_window_ms=1800,
        default_batch_max_size=7,
    )

    assert store.get_global() == GlobalTranslationSettings(
        gemini_batch_window_ms=1800,
        gemini_batch_max_size=7,
    )


def test_translation_settings_store_round_trips_global_settings(tmp_path):
    path = tmp_path / "settings.json"
    store = TranslationSettingsStore(path)

    store.save_global(
        GlobalTranslationSettings(
            gemini_batch_window_ms=2500,
            gemini_batch_max_size=12,
        )
    )

    assert store.get_global() == GlobalTranslationSettings(
        gemini_batch_window_ms=2500,
        gemini_batch_max_size=12,
    )


def test_translation_settings_store_preserves_global_when_saving_guild(tmp_path):
    path = tmp_path / "settings.json"
    store = TranslationSettingsStore(path)
    store.save_global(
        GlobalTranslationSettings(
            gemini_batch_window_ms=2500,
            gemini_batch_max_size=12,
        )
    )

    store.save(GuildTranslationSettings(guild_id=123))

    assert store.get_global() == GlobalTranslationSettings(
        gemini_batch_window_ms=2500,
        gemini_batch_max_size=12,
    )
    assert store.get(123).guild_id == 123


def test_translation_settings_store_clamps_invalid_global_values(tmp_path):
    path = tmp_path / "settings.json"
    path.write_text(
        """
        {
          "version": 1,
          "global": {
            "translation": {
              "gemini_batch_window_ms": 999999,
              "gemini_batch_max_size": 0
            }
          },
          "guilds": {}
        }
        """,
        encoding="utf-8",
    )
    store = TranslationSettingsStore(path)

    assert store.get_global() == GlobalTranslationSettings(
        gemini_batch_window_ms=10000,
        gemini_batch_max_size=1,
    )


def test_translation_settings_require_both_direction_providers():
    setting = GuildTranslationSettings(
        guild_id=123,
        source_channel_id=111,
        mirror_channel_id=222,
        providers={
            direction_key("en", "fr"): "gemini",
        },
    )

    assert setting.configured is False
