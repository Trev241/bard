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
PV_ACCESS_KEY = os.getenv("PV_ACCESS_KEY")
WATCHER_UPDATE_YTDLP_ON_RESTART = parse_bool_env("WATCHER_UPDATE_YTDLP_ON_RESTART", True)
WATCHER_YTDLP_UPDATE_TIMEOUT = parse_int_env("WATCHER_YTDLP_UPDATE_TIMEOUT", 120)
LOG_MAX_BYTES = parse_int_env("LOG_MAX_BYTES", 5 * 1024 * 1024)
LOG_BACKUP_COUNT = parse_int_env("LOG_BACKUP_COUNT", 5)
LOG_SNIPPET_LINES = parse_int_env("LOG_SNIPPET_LINES", 120)

LOG_DIR = BASE_DIR / "logs"
LOG_FILE = LOG_DIR / "bard.log"
DUMPS_DIR = BASE_DIR / "resources" / "dumps"
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
ASSISTANT_REPLY_AUDIO = ASSISTANT_RESOURCES_DIR / "reply.wav"
ASSISTANT_INCOMING_AUDIO = ASSISTANT_RESOURCES_DIR / "incoming.wav"

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
    for path in (LOG_DIR, DUMPS_DIR, STICKERS_DIR, SECRETS_DIR):
        path.mkdir(parents=True, exist_ok=True)
