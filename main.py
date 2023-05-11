import discord
import asyncio
import logging
import sys
import os

# Importing cogs
import music
import utils
import events
import wordle

from discord.ext import commands
from dotenv import load_dotenv

# LOADING ENVIRONMENT VARIABLES
load_dotenv()

# SETTING UP LOGGING
root = logging.getLogger()
root.setLevel(logging.DEBUG)

handler = logging.StreamHandler(sys.stdout)
handler.setLevel(logging.DEBUG)
formatter = logging.Formatter(
    '%(asctime)s - %(name)s - %(levelname)s - %(message)s')

handler.setFormatter(formatter)
root.addHandler(handler)

# ADDING COGS TO BOT
cogs = [music, utils, events, wordle]

# INITIALIZING CLIENT
client = commands.Bot(command_prefix='?', intents=discord.Intents.all())


async def load_extensions():
    """
    Load all extensions asynchronously by inovking the setup method of each cog.
    """

    for i in range(len(cogs)):
        await cogs[i].setup(client)


async def main():
    discord.utils.setup_logging(
        handler=handler,
        formatter=formatter,
        level=logging.ERROR,
        root=True
    )

    async with client:
        await load_extensions()
        await client.start(
            token=os.getenv('TOKEN')
        )

asyncio.run(main())
