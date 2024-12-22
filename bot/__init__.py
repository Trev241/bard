import sys
import discord
import logging
import threading

from discord.ext import commands
from datetime import datetime
from flask import Flask
from flask_socketio import SocketIO
from pathlib import Path

client = commands.Bot(command_prefix="?", intents=discord.Intents.all())
app = Flask(__name__)
socketio = SocketIO(app)

# Constants
EMBED_COLOR_THEME = 15844367
BOT_SPAM_CHANNEL = 423774455332864011


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

# Setting up logging
logger = logging.getLogger()
logger.setLevel(logging.DEBUG)
log_formatter = logging.Formatter(
    "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)

Path("bot/logs").mkdir(parents=True, exist_ok=True)
log_handlers = {
    "strm": logging.StreamHandler(sys.stdout),
    "file": logging.FileHandler(f"bot/logs/{datetime.date(datetime.now())}.txt"),
}
for log_handler in log_handlers.values():
    log_handler.setLevel(logging.DEBUG)
    log_handler.setFormatter(log_formatter)
    logger.addHandler(log_handler)
