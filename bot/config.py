import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()


BASE_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = BASE_DIR.parent

TOKEN = os.getenv("TOKEN")
WEBHOOK_SECRET = os.getenv("WEBHOOK_SECRET", "")

DASHBOARD_HOST = os.getenv("DASHBOARD_HOST", "127.0.0.1")
def parse_int_env(name, default):
    value = os.getenv(name)
    if value is None:
        return default

    try:
        return int(value)
    except ValueError as exc:
        raise ValueError(f"{name} must be an integer, got {value!r}") from exc


def parse_float_env(name, default):
    value = os.getenv(name)
    if value is None:
        return default

    try:
        return float(value)
    except ValueError as exc:
        raise ValueError(f"{name} must be a float, got {value!r}") from exc


def parse_bool_env(name, default=False):
    value = os.getenv(name)
    if value is None:
        return default

    return value.strip().casefold() in {"1", "true", "yes", "on"}


DASHBOARD_PORT = parse_int_env("DASHBOARD_PORT", 5000)
DEFAULT_PUBLIC_URL = os.getenv(
    "PUBLIC_URL", f"http://{DASHBOARD_HOST}:{DASHBOARD_PORT}"
)

BOT_SPAM_CHANNEL = parse_int_env("BOT_SPAM_CHANNEL", 423774455332864011)
COMMAND_PREFIX = os.getenv("COMMAND_PREFIX", "?")
ASSISTANT_ENABLED = parse_bool_env("ASSISTANT_ENABLED", False)
ASSISTANT_LLM_PROVIDER = os.getenv("ASSISTANT_LLM_PROVIDER", "none").strip().casefold()
ASSISTANT_LLM_TIMEOUT_SECONDS = parse_float_env("ASSISTANT_LLM_TIMEOUT_SECONDS", 2.0)
ASSISTANT_LLM_MIN_CONFIDENCE = parse_float_env("ASSISTANT_LLM_MIN_CONFIDENCE", 0.75)
ASSISTANT_TRANSCRIPTION_TIMEOUT_SECONDS = parse_float_env(
    "ASSISTANT_TRANSCRIPTION_TIMEOUT_SECONDS", 12.0
)
ASSISTANT_WAKEWORD_MODELS = [
    model.strip()
    for model in os.getenv("ASSISTANT_WAKEWORD_MODELS", "hey jarvis").split(",")
    if model.strip()
]
ASSISTANT_WAKEWORD_THRESHOLD = parse_float_env("ASSISTANT_WAKEWORD_THRESHOLD", 0.5)
ASSISTANT_OPENROUTER_API_KEY = os.getenv("ASSISTANT_OPENROUTER_API_KEY", "")
ASSISTANT_OPENROUTER_MODEL = os.getenv("ASSISTANT_OPENROUTER_MODEL", "")
WATCHER_UPDATE_YTDLP_ON_RESTART = parse_bool_env("WATCHER_UPDATE_YTDLP_ON_RESTART", True)
WATCHER_YTDLP_UPDATE_TIMEOUT = parse_int_env("WATCHER_YTDLP_UPDATE_TIMEOUT", 120)
LOG_MAX_BYTES = parse_int_env("LOG_MAX_BYTES", 5 * 1024 * 1024)
LOG_BACKUP_COUNT = parse_int_env("LOG_BACKUP_COUNT", 5)
LOG_SNIPPET_LINES = parse_int_env("LOG_SNIPPET_LINES", 120)
GITHUB_REPO = os.getenv("GITHUB_REPO", "")
GITHUB_TOKEN = os.getenv("GITHUB_TOKEN", "")
GITHUB_ISSUE_LABELS = [
    label.strip()
    for label in os.getenv("GITHUB_ISSUE_LABELS", "bug,user-report").split(",")
    if label.strip()
]
TRANSLATION_ENABLED = parse_bool_env("TRANSLATION_ENABLED", False)
TRANSLATION_PROVIDER = os.getenv("TRANSLATION_PROVIDER", "argos").strip().casefold()
TRANSLATION_CHANNEL_PAIRS = os.getenv("TRANSLATION_CHANNEL_PAIRS", "")
TRANSLATION_CACHE_SIZE = parse_int_env("TRANSLATION_CACHE_SIZE", 1000)
TRANSLATION_MAX_CONCURRENCY = parse_int_env("TRANSLATION_MAX_CONCURRENCY", 1)
TRANSLATION_MAX_MESSAGE_LENGTH = parse_int_env("TRANSLATION_MAX_MESSAGE_LENGTH", 1500)
TRANSLATION_USE_WEBHOOKS = parse_bool_env("TRANSLATION_USE_WEBHOOKS", True)
WRITING_FEEDBACK_ENABLED = parse_bool_env("WRITING_FEEDBACK_ENABLED", False)
WRITING_FEEDBACK_AUTO_REPLY = parse_bool_env("WRITING_FEEDBACK_AUTO_REPLY", False)
WRITING_FEEDBACK_PROVIDER = os.getenv(
    "WRITING_FEEDBACK_PROVIDER", "grammalecte"
).strip().casefold()
WRITING_FEEDBACK_LANGUAGES = {
    language.strip().casefold()
    for language in os.getenv("WRITING_FEEDBACK_LANGUAGES", "fr").split(",")
    if language.strip()
}
WRITING_FEEDBACK_SCORE_THRESHOLD = parse_int_env(
    "WRITING_FEEDBACK_SCORE_THRESHOLD", 75
)
WRITING_FEEDBACK_RECOMMEND_THRESHOLD = parse_int_env(
    "WRITING_FEEDBACK_RECOMMEND_THRESHOLD", 45
)
WRITING_FEEDBACK_MAX_ISSUES = parse_int_env("WRITING_FEEDBACK_MAX_ISSUES", 3)
WRITING_FEEDBACK_LLM_PROVIDER = os.getenv(
    "WRITING_FEEDBACK_LLM_PROVIDER", "none"
).strip().casefold()
WRITING_FEEDBACK_GEMINI_API_KEY = os.getenv("WRITING_FEEDBACK_GEMINI_API_KEY", "")
WRITING_FEEDBACK_GEMINI_MODEL = os.getenv(
    "WRITING_FEEDBACK_GEMINI_MODEL",
    "gemini-3.5-flash",
)
WRITING_FEEDBACK_LLM_TIMEOUT_SECONDS = parse_float_env(
    "WRITING_FEEDBACK_LLM_TIMEOUT_SECONDS", 4.0
)
WRITING_FEEDBACK_LLM_RATE_LIMIT_COOLDOWN_SECONDS = parse_float_env(
    "WRITING_FEEDBACK_LLM_RATE_LIMIT_COOLDOWN_SECONDS", 300.0
)


def parse_translation_channel_pairs(value=None):
    raw_value = TRANSLATION_CHANNEL_PAIRS if value is None else value
    pairs = []

    for raw_pair in raw_value.split(","):
        raw_pair = raw_pair.strip()
        if not raw_pair:
            continue

        parts = [part.strip() for part in raw_pair.split(":")]
        if len(parts) != 4:
            raise ValueError(
                "TRANSLATION_CHANNEL_PAIRS entries must use "
                "source_channel_id:mirror_channel_id:source_lang:mirror_lang"
            )

        source_channel_id, mirror_channel_id, source_lang, mirror_lang = parts
        pairs.append(
            {
                "source_channel_id": int(source_channel_id),
                "mirror_channel_id": int(mirror_channel_id),
                "source_lang": source_lang,
                "mirror_lang": mirror_lang,
            }
        )

    return pairs

LOG_DIR = BASE_DIR / "logs"
LOG_FILE = LOG_DIR / "bard.log"
DUMPS_DIR = BASE_DIR / "resources" / "dumps"
ASSISTANT_RUNTIME_DIR = DUMPS_DIR / "assistant"
STICKERS_DIR = BASE_DIR / "resources" / "stickers"
SECRETS_DIR = BASE_DIR / "secrets"
ASSISTANT_RESOURCES_DIR = BASE_DIR / "resources" / "assistant"
SOUNDS_DIR = BASE_DIR / "resources" / "sounds"
FONTS_DIR = BASE_DIR / "resources" / "fonts"

COOKIES_FILE = SECRETS_DIR / "cookies.txt"
HEAD_COMMIT_DUMP = DUMPS_DIR / "head-commit.json"
ENTRIES_DUMP = DUMPS_DIR / "entries.json"
YTDLP_DUMP = DUMPS_DIR / "yt-dlp.json"
YORDLE_IMAGE = DUMPS_DIR / "yordle_word.png"
DROID_MONO_FONT = FONTS_DIR / "DroidSansMono.ttf"

RESTART_SIGNAL_FILE = BASE_DIR / "restart_signal.flag"
RESTART_SIGNAL_TRIGGER_FILE = BASE_DIR / "restart_signal_trigger.flag"
DISCONNECT_SOUND = SOUNDS_DIR / "bard.disconnect.ogg"

ASSISTANT_DIALOGS = ASSISTANT_RESOURCES_DIR / "dialogs.json"
ASSISTANT_CONTEXT = ASSISTANT_RESOURCES_DIR / "Bard Assistant.yml"
ASSISTANT_REPLY_AUDIO = ASSISTANT_RUNTIME_DIR / "reply.wav"
ASSISTANT_INCOMING_AUDIO = ASSISTANT_RUNTIME_DIR / "incoming.wav"

AUTOPLAY_PLAYLIST_URL = os.getenv(
    "AUTOPLAY_PLAYLIST_URL",
    "https://www.youtube.com/playlist?list=PL7Akty-aEXMq8x9ToQy7v4TxLsi42MHSd",
)

ADMIN_IDS = {
    int(item)
    for item in os.getenv("BARD_ADMIN_IDS", "").replace(" ", "").split(",")
    if item
}


def ensure_runtime_dirs():
    for path in (LOG_DIR, DUMPS_DIR, ASSISTANT_RUNTIME_DIR, STICKERS_DIR, SECRETS_DIR):
        path.mkdir(parents=True, exist_ok=True)
