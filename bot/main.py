import discord
import asyncio
import logging
import sys
import os

# Importing cogs
import cogs.music as music
import cogs.utils as utils
import cogs.events as events
import cogs.wordle as wordle
import cogs.assistant as assistant

from discord.ext import commands
from dotenv import load_dotenv
from datetime import datetime
from pathlib import Path

# LOADING ENVIRONMENT VARIABLES
load_dotenv()
TOKEN = os.getenv("TOKEN")

# SETTING UP LOGGING
root = logging.getLogger()
root.setLevel(logging.DEBUG)

formatter = logging.Formatter("%(asctime)s - %(name)s - %(levelname)s - %(message)s")

Path("logs").mkdir(parents=True, exist_ok=True)

# Handlers
strm_handler = logging.StreamHandler(sys.stdout)
strm_handler.setLevel(logging.DEBUG)
strm_handler.setFormatter(formatter)
file_handler = logging.FileHandler(f"logs/{datetime.date(datetime.now())}.txt")
file_handler.setLevel(logging.DEBUG)
file_handler.setFormatter(formatter)

root.addHandler(strm_handler)
root.addHandler(file_handler)

# ADDING COGS TO BOT
cogs = [music, utils, events, wordle, assistant]

# INITIALIZING CLIENT
client = commands.Bot(command_prefix="?", intents=discord.Intents.all())


async def load_extensions():
    """
    Load all extensions asynchronously by inovking the setup method of each cog.
    """

    for i in range(len(cogs)):
        await cogs[i].setup(client)


async def main():
    discord.utils.setup_logging(
        handler=strm_handler, formatter=formatter, level=logging.INFO, root=True
    )

    async with client:
        await load_extensions()
        await client.start(token=TOKEN)


if __name__ == "__main__":
    asyncio.run(main())
