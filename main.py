import discord
import asyncio
import logging
import sys

# Importing cogs
import music

from discord.ext import commands

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
            token="MTA0OTU1MjgzNjg5NzI4NDE5Ng.G6Ld6A.ZJBb5P58EUmXHbDJPU62jZblHX2r8vBxNDhAvY"
        )

asyncio.run(main())