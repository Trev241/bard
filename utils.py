import discord
import asyncio

from constants import PING_DELAY
from discord.ext import commands

class Utils(commands.Cog):
    def __init__(self, client):
        self.client = client
        self.is_pinging = False
        self.ctx = None

    @commands.command()
    async def ping(self, ctx, who: discord.Member, limit: int = 100):
        if self.is_pinging:
            await ctx.send(f'Waiting for old pinging routine to end...')
            await self.ping_stop(ctx)

        self.who = who
        self.ping_limit = limit
        self.ping_count = 0
        self.ctx = ctx

        el = asyncio.get_event_loop()
        el.create_task(self.pinging(ctx))

    @commands.command()
    async def ping_stop(self, ctx):
        self.is_pinging = False
        await asyncio.sleep(PING_DELAY + 1)

    async def pinging(self, ctx):
        self.is_pinging = True
        while self.is_pinging and self.ping_count < self.ping_limit:
            await ctx.send(f'{self.who.mention} ({self.ping_count + 1}/{self.ping_limit})')
            await asyncio.sleep(PING_DELAY)
            self.ping_count += 1
        self.is_pinging = False

async def setup(client):
    await client.add_cog(Utils(client))