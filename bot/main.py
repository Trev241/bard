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
from bot import client, log_handlers, log_formatter
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


event_loop = None


async def main():
    global event_loop
    event_loop = asyncio.get_event_loop()
    discord.utils.setup_logging(
        handler=log_handlers["strm"],
        formatter=log_formatter,
        level=logging.INFO,
        root=True,
    )

    async with client:
        await load_extensions()
        await client.start(token=TOKEN)


def start():
    asyncio.run(main())


if __name__ == "__main__":
    # Create worker thread for the bot application
    threading.Thread(target=start, daemon=True).start()
    run_flask()
