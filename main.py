import discord
import asyncio
import logging
import sys
import json

# Importing cogs
import music

from discord.ext import commands

# READING CONFIG AND FETCHING TOKEN
with open('config.json') as config_file:
    config = json.load(config_file)

# SETTING UP LOGGING
root = logging.getLogger()
root.setLevel(logging.DEBUG)

handler = logging.StreamHandler(sys.stderr)
handler.setLevel(logging.DEBUG)
formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')

handler.setFormatter(formatter)
root.addHandler(handler)

# ADDING COGS TO BOT
cogs = [music]

# INITIALIZING CLIENT
client = commands.Bot(command_prefix='?', intents=discord.Intents.all())

async def load_extensions():
    '''
    Load all extensions asynchornously by inovking the setup method of each cog.
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
            token=config['token']
        )

asyncio.run(main())