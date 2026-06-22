import asyncio
import logging
import sys

import discord
from discord.ext import commands

from bot import config
from bot.core.checks import trusted_only
from bot.core.logging_service import recent_log_text

log = logging.getLogger(__name__)


class Utils(commands.Cog):
    PING_DELAY = 2.0

    def __init__(self, client):
        self.client = client
        self.is_pinging = False
        self.channel = None
        self.ping_who = {}
        self.pinging_task = None

    @commands.group(name="ping", invoke_without_command=True)
    @trusted_only
    async def issue_ping(self, ctx, who: discord.Member, limit: int = 100):
        await self.ping(ctx.message.channel, [who], limit)

    async def ping(self, channel, who, limit: int = 100):
        for member in who:
            self.ping_who[member] = limit

        self.ping_limit = max(self.ping_who.values())
        self.ping_count = 0
        self.channel = channel

        if not self.is_pinging:
            loop = asyncio.get_event_loop()
            self.pinging_task = loop.create_task(self.pinging(channel))

    @issue_ping.command(
        name="stop",
        aliases=["halt", "remove", "terminate", "end", "done", "finish", "over"],
    )
    @trusted_only
    async def ping_stop(self, ctx):
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

            if ping_message == "":
                break

            await channel.send(ping_message)
            await asyncio.sleep(Utils.PING_DELAY)
            self.ping_count += 1

        self.is_pinging = False
        self.ping_who = {}

    @commands.command()
    @trusted_only
    async def restart(self, ctx):
        await ctx.send("Restarting...")
        with open(config.RESTART_SIGNAL_TRIGGER_FILE, "w") as fp:
            fp.write("restart")

    @commands.group(name="logs", invoke_without_command=True)
    @trusted_only
    async def logs(self, ctx, lines: int = config.LOG_SNIPPET_LINES):
        lines = max(1, min(lines, 300))
        log_text = recent_log_text(max_lines=lines)
        if not log_text:
            await ctx.send("No logs are available yet.")
            return

        snippet = log_text[-1800:]
        if len(snippet) < len(log_text):
            snippet = f"... truncated to fit Discord message limits ...\n{snippet}"

        snippet = snippet.replace("```", "` ` `")
        await ctx.send(f"```text\n{snippet}\n```")

    @logs.command(name="full")
    @trusted_only
    async def logs_full(self, ctx):
        if not config.LOG_FILE.exists():
            await ctx.send("No log file is available yet.")
            return

        await ctx.send(file=discord.File(config.LOG_FILE))

    @commands.command()
    @trusted_only
    async def shutdown(self, ctx):
        await ctx.send("Going to sleep...")
        sys.exit(0)


async def setup(client):
    await client.add_cog(Utils(client))
