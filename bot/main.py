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
        flask_thread = threading.Thread(target=run_flask, args=(client,), daemon=True)
        flask_thread.start()

        print("before start")
        await client.start(token=TOKEN)
        print("after start")
        flask_thread.join()


def start():
    asyncio.run(main())


if __name__ == "__main__":
    # Create worker thread for the bot application
    threading.Thread(target=start).start()

    while True:
        restart_event.wait()
        restart_event.clear()

        os.execv(sys.executable, ["python"] + sys.argv)
