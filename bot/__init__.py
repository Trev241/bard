import sys

from flask import Flask
from flask_socketio import SocketIO
from discord.ext import commands
import discord

from bot import config
from bot.core.logging_service import configure_logging


config.ensure_runtime_dirs()

client = commands.Bot(command_prefix=config.COMMAND_PREFIX, intents=discord.Intents.all())
app = Flask(
    __name__,
    template_folder=str(config.BASE_DIR / "dashboard" / "templates"),
    static_folder=str(config.BASE_DIR / "dashboard" / "static"),
)
app.secret_key = config.DASHBOARD_SECRET_KEY or config.TOKEN or "bard-dashboard-dev"
socketio = SocketIO(app)

public_url = config.DEFAULT_PUBLIC_URL

# Constants
EMBED_COLOR_THEME = 15844367
BOT_SPAM_CHANNEL = config.BOT_SPAM_CHANNEL


class StdoutHandler:
    def __init__(self):
        self._original_stdout = sys.stdout
        sys.stdout = self

    def write(self, message):
        if message.strip():
            socketio.emit("stdout_message", {"message": message})
        self._original_stdout.write(message)

    def flush(self):
        self._original_stdout.flush()

    def restore(self):
        sys.stdout = self._original_stdout


class StderrHandler:
    def __init__(self):
        self._original_stderr = sys.stderr
        sys.stderr = self

    def write(self, message):
        if message.strip():
            socketio.emit("stderr_message", {"message": message})
        self._original_stderr.write(message)

    def flush(self):
        self._original_stderr.flush()

    def restore(self):
        sys.stderr = self._original_stderr


# Intercepting stdout
# stdout_handler = StdoutHandler()
# stderr_handler = StderrHandler()

log_handlers, log_formatter = configure_logging()
