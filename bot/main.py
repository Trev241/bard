import discord
import asyncio
import logging
import os
import sys
import threading

# Importing cogs
import bot.cogs.music as music
import bot.cogs.utils as utils
import bot.cogs.events as events
import bot.cogs.wordle as wordle
import bot.cogs.assistant as assistant
import bot.cogs.analytics as analytics

from dotenv import load_dotenv
from bot import client, log_handlers, log_formatter, restart_event
from bot.app import run_flask

# LOADING ENVIRONMENT VARIABLES
load_dotenv()
TOKEN = os.getenv("TOKEN")

logger = logging.getLogger(__name__)

# ADDING COGS TO BOT
cogs = [music, utils, events, wordle, assistant, analytics]


async def load_extensions():
    """Load all extensions asynchronously by inovking the setup method of each cog."""

    for i in range(len(cogs)):
        await cogs[i].setup(client)


async def main():
    discord.utils.setup_logging(
        handler=log_handlers["strm"],
        formatter=log_formatter,
        level=logging.INFO,
        root=True,
    )

    async with client:
        await load_extensions()
        # Create worker thread for the flask application

        await client.start(token=TOKEN)
        flask_thread.join()


event_loop


def start():
    global event_loop
    asyncio.run(main())
    event_loop = asyncio.get_event_loop()


if __name__ == "__main__":
    global event_loop
    # Create worker thread for the bot application
    threading.Thread(target=start, daemon=True).start()
    flask_thread = threading.Thread(target=run_flask, daemon=True)
    flask_thread.start()

    while True:
        restart_event.wait()
        restart_event.clear()

        logger.info("Restart event was set. Commencing procedure to restart.")
        logger.info("Stopping bot event loop...")
        event_loop.stop()
        logger.info("Success! Bot event loop closed.")
        logger.info("Waiting for Flask to shutdown...")
        flask_thread.join()
        logger.info("Success! Flask shutdown successfully.")

        # script_dir = os.path.dirname(os.path.abspath(sys.argv[0]))
        # os.chdir(script_dir)
        # os.execv(sys.executable, [sys.executable, "-m", "bot.main"] + sys.argv[1:])
        os.execv(sys.executable, ["python", "-m", "bot.main"] + sys.argv[1:])
