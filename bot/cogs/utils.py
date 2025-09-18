import discord
import asyncio
import sys
import logging

from discord.ext import commands
from datetime import datetime

log = logging.getLogger(__name__)


class Utils(commands.Cog):
    PING_DELAY = 2.0

    def __init__(self, client):
        self.client = client
        self.is_pinging = False
        self.channel = None
        self.ping_who = {}

    @commands.group(name="ping", invoke_without_command=True)
    async def issue_ping(self, ctx, who: discord.Member, limit: int = 100):
        await self.ping(ctx.message.channel, [who], limit)

    async def ping(self, channel, who, limit: int = 100):
        # Set a ping limit for all new members to be pinged
        for member in who:
            self.ping_who[member] = limit

        # Find out who will be pinged last
        self.ping_limit = max(self.ping_who.values())
        self.ping_count = 0
        self.channel = channel

        # Start a new pinging task if it does not already exist
        if not self.is_pinging:
            el = asyncio.get_event_loop()
            self.pinging_task = el.create_task(self.pinging(channel))

    @issue_ping.command(
        name="stop",
        aliases=["halt", "remove", "terminate", "end", "done", "finish", "over"],
    )
    async def ping_stop(self, ctx):
        # Reset everything
        self.is_pinging = False
        self.ping_who = {}

        if self.pinging_task:
            self.pinging_task.cancel()

    async def pinging(self, channel):
        self.is_pinging = True
        while (
            self.is_pinging
            and self.ping_count <= self.ping_limit
            and len(self.ping_who) > 0
        ):
            ping_message = ""
            for member, count in self.ping_who.items():
                if count > 0:
                    ping_message += f"{member.mention} ({count}) "
                    self.ping_who[member] -= 1

            # It's possible that everyone might reply leaving the ping string empty
            if ping_message == "":
                break

            await channel.send(ping_message)
            await asyncio.sleep(Utils.PING_DELAY)
            self.ping_count += 1

        self.is_pinging = False
        self.ping_who = {}

    @commands.command()
    async def logs(self, ctx):
        await ctx.send(file=discord.File(f"logs/{datetime.date(datetime.now())}.txt"))

    @commands.command()
    async def shutdown(self, ctx):
        await ctx.send("Going to sleep...")
        sys.exit(0)


async def setup(client):
    await client.add_cog(Utils(client))
