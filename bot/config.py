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
DASHBOARD_AUTH_ENABLED = parse_bool_env("DASHBOARD_AUTH_ENABLED", True)
DASHBOARD_SECRET_KEY = os.getenv("DASHBOARD_SECRET_KEY", WEBHOOK_SECRET or "")
DASHBOARD_DISCORD_CLIENT_ID = os.getenv("DASHBOARD_DISCORD_CLIENT_ID", "")
DASHBOARD_DISCORD_CLIENT_SECRET = os.getenv("DASHBOARD_DISCORD_CLIENT_SECRET", "")
DASHBOARD_DISCORD_REDIRECT_URI = os.getenv(
    "DASHBOARD_DISCORD_REDIRECT_URI",
    f"{DEFAULT_PUBLIC_URL}/dashboard/auth/callback",
)

BOT_SPAM_CHANNEL = parse_int_env("BOT_SPAM_CHANNEL", 423774455332864011)
COMMAND_PREFIX = os.getenv("COMMAND_PREFIX", "?")
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
TRANSLATION_CACHE_SIZE = parse_int_env("TRANSLATION_CACHE_SIZE", 1000)
TRANSLATION_PERSISTENT_CACHE_ENABLED = parse_bool_env(
    "TRANSLATION_PERSISTENT_CACHE_ENABLED",
    True,
)
TRANSLATION_MAX_CONCURRENCY = parse_int_env("TRANSLATION_MAX_CONCURRENCY", 1)
TRANSLATION_MAX_MESSAGE_LENGTH = parse_int_env("TRANSLATION_MAX_MESSAGE_LENGTH", 1500)
TRANSLATION_USE_WEBHOOKS = parse_bool_env("TRANSLATION_USE_WEBHOOKS", True)
TRANSLATION_NORMALIZE_SLANG = parse_bool_env("TRANSLATION_NORMALIZE_SLANG", True)
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
WRITING_FEEDBACK_AUTO_REWRITE_THRESHOLD = parse_int_env(
    "WRITING_FEEDBACK_AUTO_REWRITE_THRESHOLD", 25
)
WRITING_FEEDBACK_MAX_ISSUES = parse_int_env("WRITING_FEEDBACK_MAX_ISSUES", 3)
WRITING_FEEDBACK_LLM_PROVIDER = os.getenv(
    "WRITING_FEEDBACK_LLM_PROVIDER", "none"
).strip().casefold()
WRITING_FEEDBACK_LLM_EXTRA_INSTRUCTIONS = (
    os.getenv("WRITING_FEEDBACK_LLM_EXTRA_INSTRUCTIONS", "")
    .replace("\\n", "\n")
    .strip()
)
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


LOG_DIR = BASE_DIR / "logs"
LOG_FILE = LOG_DIR / "bard.log"
DUMPS_DIR = BASE_DIR / "resources" / "dumps"
TRANSLATION_RESOURCES_DIR = BASE_DIR / "resources" / "translation"
STICKERS_DIR = BASE_DIR / "resources" / "stickers"
SECRETS_DIR = BASE_DIR / "secrets"
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
TRANSLATION_GUILD_SETTINGS_FILE = TRANSLATION_RESOURCES_DIR / "settings.json"
TRANSLATION_CACHE_FILE = Path(
    os.getenv(
        "TRANSLATION_CACHE_FILE",
        str(TRANSLATION_RESOURCES_DIR / "cache.sqlite3"),
    )
)

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
    for path in (LOG_DIR, DUMPS_DIR, TRANSLATION_RESOURCES_DIR, STICKERS_DIR, SECRETS_DIR):
        path.mkdir(parents=True, exist_ok=True)
