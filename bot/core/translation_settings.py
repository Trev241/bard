import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Dict, Iterable, Optional, Tuple


@dataclass(frozen=True)
class GuildTranslationSettings:
    guild_id: int
    source_channel_id: Optional[int] = None
    mirror_channel_id: Optional[int] = None
    source_lang: str = "en"
    mirror_lang: str = "fr"
    providers: Dict[str, str] = field(default_factory=dict)
    auto_rewrite_enabled: bool = False
    auto_rewrite_threshold: int = 25
    llm_extra_instructions: str = ""

    @property
    def configured(self) -> bool:
        return bool(self.source_channel_id and self.mirror_channel_id)

    def provider_for(self, source: str, target: str, default: str = "argos") -> str:
        return self.providers.get(
            direction_key(source, target),
            default,
        ).strip().casefold()


class TranslationSettingsStore:
    def __init__(self, path: Path):
        self.path = Path(path)

    def load_all(self) -> Dict[int, GuildTranslationSettings]:
        if not self.path.exists():
            return {}

        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {}

        settings = {}
        for guild_id, raw_settings in (data.get("guilds") or {}).items():
            try:
                setting = self._setting_from_data(int(guild_id), raw_settings)
            except (TypeError, ValueError):
                continue
            settings[setting.guild_id] = setting
        return settings

    def get(self, guild_id: int) -> GuildTranslationSettings:
        return self.load_all().get(
            int(guild_id),
            GuildTranslationSettings(guild_id=int(guild_id)),
        )

    def save(self, setting: GuildTranslationSettings) -> None:
        settings = self.load_all()
        settings[setting.guild_id] = setting
        self.save_all(settings.values())

    def save_all(self, settings: Iterable[GuildTranslationSettings]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        data = {
            "version": 1,
            "guilds": {
                str(setting.guild_id): self._setting_to_data(setting)
                for setting in settings
            },
        }
        self.path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")

    @staticmethod
    def _setting_from_data(guild_id: int, data: dict) -> GuildTranslationSettings:
        return GuildTranslationSettings(
            guild_id=guild_id,
            source_channel_id=optional_int(data.get("source_channel_id")),
            mirror_channel_id=optional_int(data.get("mirror_channel_id")),
            source_lang=str(data.get("source_lang") or "en").strip().casefold(),
            mirror_lang=str(data.get("mirror_lang") or "fr").strip().casefold(),
            providers={
                str(key).strip().casefold(): str(value).strip().casefold()
                for key, value in (data.get("providers") or {}).items()
                if str(key).strip() and str(value).strip()
            },
            auto_rewrite_enabled=bool(data.get("auto_rewrite_enabled", False)),
            auto_rewrite_threshold=clamp_score(data.get("auto_rewrite_threshold", 25)),
            llm_extra_instructions=str(data.get("llm_extra_instructions") or ""),
        )

    @staticmethod
    def _setting_to_data(setting: GuildTranslationSettings) -> dict:
        data = asdict(setting)
        data.pop("guild_id", None)
        return data


def settings_from_legacy_env(guild_ids: Iterable[int], config) -> Dict[int, GuildTranslationSettings]:
    pairs = config.parse_translation_channel_pairs()
    providers_by_direction = config.parse_translation_provider_by_direction()
    settings = {}
    guild_id_list = [int(item) for item in guild_ids]

    for index, pair in enumerate(pairs):
        if not guild_id_list:
            break
        guild_id = guild_id_list[min(index, len(guild_id_list) - 1)]
        source_lang = pair["source_lang"]
        mirror_lang = pair["mirror_lang"]
        source_to_mirror = providers_by_direction.get(
            (source_lang.casefold(), mirror_lang.casefold()),
            config.TRANSLATION_PROVIDER,
        )
        mirror_to_source = providers_by_direction.get(
            (mirror_lang.casefold(), source_lang.casefold()),
            config.TRANSLATION_PROVIDER,
        )
        settings[guild_id] = GuildTranslationSettings(
            guild_id=guild_id,
            source_channel_id=pair["source_channel_id"],
            mirror_channel_id=pair["mirror_channel_id"],
            source_lang=source_lang,
            mirror_lang=mirror_lang,
            providers={
                direction_key(source_lang, mirror_lang): source_to_mirror,
                direction_key(mirror_lang, source_lang): mirror_to_source,
            },
            auto_rewrite_enabled=config.WRITING_FEEDBACK_AUTO_REPLY,
            auto_rewrite_threshold=config.WRITING_FEEDBACK_AUTO_REWRITE_THRESHOLD,
            llm_extra_instructions=config.WRITING_FEEDBACK_LLM_EXTRA_INSTRUCTIONS,
        )

    return settings


def direction_key(source: str, target: str) -> str:
    return f"{source.strip().casefold()}->{target.strip().casefold()}"


def direction_tuple(key: str) -> Tuple[str, str]:
    source, target = key.split("->", 1)
    return source.strip().casefold(), target.strip().casefold()


def optional_int(value):
    if value in {None, ""}:
        return None
    return int(value)


def clamp_score(value) -> int:
    try:
        score = int(value)
    except (TypeError, ValueError):
        score = 25
    return max(0, min(score, 100))
