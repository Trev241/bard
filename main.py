import discord
import asyncio
import logging
import sys
import json

# Importing cogs
import music
import utils
import events

from discord.ext import commands

# FETCHING TOKEN
with open('secrets.json') as f:
    secrets = json.load(f)

# SETTING UP LOGGING
root = logging.getLogger()
root.setLevel(logging.DEBUG)

handler = logging.StreamHandler(sys.stdout)
handler.setLevel(logging.DEBUG)
formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')

handler.setFormatter(formatter)
root.addHandler(handler)

# ADDING COGS TO BOT
cogs = [music, utils, events]

# INITIALIZING CLIENT
client = commands.Bot(command_prefix='?', intents=discord.Intents.all())

async def load_extensions():
    '''
    Load all extensions asynchronously by inovking the setup method of each cog.
    '''
    
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
            token=secrets['token']
        )

asyncio.run(main())