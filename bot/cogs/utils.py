import asyncio
import sys
import os
import requests

from discord.ext import commands


class Utils(commands.Cog):
    PING_DELAY = 1

    def __init__(self, client):
        self.client = client
        self.is_pinging = False
        self.channel = None

    @commands.command(name="ping")
    async def issue_ping(self, ctx, who, limit: int = 100):
        self.ping(ctx.message.channel, who, limit)

    async def ping(self, channel, who, limit: int = 100):
        if self.is_pinging:
            await channel.send(f"Waiting for old pinging routine to end...")
            await self.ping_stop(channel)

        self.who = who if type(who) == list else [who]
        self.ping_limit = limit
        self.ping_count = 0
        self.channel = channel

        el = asyncio.get_event_loop()
        el.create_task(self.pinging(channel))

    @commands.command()
    async def ping_stop(self, ctx):
        self.is_pinging = False

    async def pinging(self, channel):
        self.is_pinging = True
        while (
            self.is_pinging and self.ping_count < self.ping_limit and len(self.who) > 0
        ):
            await channel.send(
                f"{' '.join([member.mention for member in self.who])} ({self.ping_count + 1}/{self.ping_limit})"
            )
            await asyncio.sleep(Utils.PING_DELAY)
            self.ping_count += 1
        self.is_pinging = False

    @commands.command()
    async def shutdown(self, ctx):
        await ctx.send("Going to sleep...")

        headers = {"secret": os.getenv("SECRET")}
        payload = {"running": False}

        try:
            res = requests.post(
                f'{os.getenv("API_BASE_URL")}/notify', json=payload, headers=headers
            )
        except:
            print(f"Request failed with code {res.status_code}. Exiting anyways.")
        finally:
            sys.exit(0)


async def setup(client):
    await client.add_cog(Utils(client))
