import logging
import os
import re
import traceback
from asyncio import TimeoutError
from datetime import datetime
from zoneinfo import ZoneInfo

import discord
import parsedatetime as pdt
from discord import Message, MessageType, RawReactionActionEvent
from discord.errors import ClientException
from discord.ext import commands
from discord.ext.commands.errors import CheckFailure, CommandNotFound

from bot import config
from bot.cogs.music import Music
from bot.core.checks import TrustedUserRequired, is_trusted_user
from bot.core.exceptions import (
    AlreadyConnected,
    AlreadyConnecting,
    CannotCompleteAction,
    ConnectionNotReady,
    UserNotInVoice,
)
from bot.core.timezones import resolve_timezone

log = logging.getLogger(__name__)


class Events(commands.Cog):
    COOKIE = "\U0001f36a"

    AUTO_PING_THRESHOLD = 2
    AUTO_PING_MAX_INTEVAL = 5

    TIMEZONES = [
        "Asia/Kolkata",
        "Australia/Sydney",
        "Europe/London",
        "America/Toronto",
        "America/Los_Angeles",
    ]

    TIME_ANCHORS = re.compile(
        r"\b("
        r"at|in|by|around|after|before|"
        r"am|pm|"
        r"\d{1,2}:\d{2}|"
        r"today|tomorrow|tonight|"
        r"tmr|tmrw|"
        r"next\s+(hour|day|week)|"
        r"in\s+\d+\s*(minute|minutes|hour|hours)|"
        r"\d+\s*(minute|minutes|hour|hours)\s+from\s+now"
        r")",
        re.IGNORECASE,
    )

    CLOCK_TIME = re.compile(
        r"\b\d{1,2}(:\d{2})?\s*(am|pm)\b|\b\d{1,2}:\d{2}\b",
        re.IGNORECASE,
    )

    RELATIVE_TIME = re.compile(
        r"\b("
        r"in\s+\d+\s*(minute|minutes|hour|hours)|"
        r"\d+\s*(minute|minutes|hour|hours)\s+from\s+now"
        r")\b",
        re.IGNORECASE,
    )

    TIME_INTENT_POSITIVE = re.compile(
        r"\b("
        r"meet|meeting|call|join|start|starts|starting|"
        r"due|deadline|remind|available|free|"
        r"at|by|around|before|after|from\s+now"
        r")\b",
        re.IGNORECASE,
    )

    TIME_INTENT_NEGATIVE = re.compile(
        r"\b("
        r"completed|finished|done|took|spent|waited|lasted|"
        r"was|were|ago"
        r")\b",
        re.IGNORECASE,
    )

    SUSPICIOUS_NUM = re.compile(r"\b0?\d{3,}\b")

    def __init__(self, client):
        self.client = client
        self._last_message = None
        self._repetitions = 0
        self.calendar = pdt.Calendar()

        self.stickers = {}
        for file in os.listdir(config.STICKERS_DIR):
            name = file.split(".")[0]
            self.stickers[name] = config.STICKERS_DIR / file

    @commands.Cog.listener()
    async def on_message(self, message: Message):
        if message.author.id == self.client.user.id:
            return

        util_base = self.client.get_cog("Utils")
        if util_base and util_base.is_pinging and util_base.ping_who.get(message.author, 0) > 0:
            util_base.ping_who[message.author] = 0
            await util_base.channel.send("You're back!")

        wordle_base = self.client.get_cog("Wordle")
        if wordle_base:
            await wordle_base.guess(message.content, message.author)

        if (
            util_base
            and self._last_message
            and len(message.mentions) > 0
            and set(self._last_message.mentions) == set(message.mentions)
            and message.type == MessageType.default
            and (message.created_at - self._last_message.created_at).total_seconds()
            < Events.AUTO_PING_MAX_INTEVAL
        ):
            self._repetitions += 1

            if self._repetitions >= Events.AUTO_PING_THRESHOLD:
                ctx = await self.client.get_context(message)
                if await is_trusted_user(ctx):
                    await util_base.ping(message.channel, message.mentions, 25)
                self._repetitions = 0
        else:
            self._repetitions = 0

        for name, path in self.stickers.items():
            if re.search(rf"\b{name}\b", message.content, re.IGNORECASE):
                sticker_file = discord.File(fp=path)
                await message.channel.send(file=sticker_file)

        local_tz = None
        for role in getattr(message.author, "roles", []):
            local_tz = resolve_timezone(role.name)
            if local_tz:
                break

        if local_tz:
            timestamp = self.parse_time_reference(message.content, local_tz)
            if timestamp:
                select = discord.ui.Select(
                    placeholder="Check other timezones with Chronokeeper"
                )
                for tz in Events.TIMEZONES:
                    ts = timestamp.astimezone(ZoneInfo(tz))
                    ts_str = ts.strftime("%H:%M - %a, %b %d ")
                    hr = ts.hour
                    is_day = hr >= 8 and hr < 20

                    select.add_option(
                        label=f"{ts_str}",
                        description=f"{ZoneInfo(tz).key}",
                        emoji="\u2600\ufe0f" if is_day else "\U0001f319",
                    )

                async def callback(interaction: discord.Interaction):
                    await interaction.response.defer()

                select.callback = callback

                view = discord.ui.View()
                view.add_item(select)
                await message.reply(view=view)
        else:
            log.debug("No timezone role found for %s.", message.author)

        self._last_message = message

    def parse_time_reference(self, content, local_tz):
        if not self.should_attempt_timezone_conversion(content):
            return None

        local_base_time = datetime.now().astimezone(local_tz)
        timestamp, status = self.calendar.parseDT(content, local_base_time)
        if status <= 1:
            log.debug("parsedatetime did not find a usable time in: %s", content)
            return None

        return timestamp.replace(tzinfo=local_tz)

    @staticmethod
    def should_attempt_timezone_conversion(content):
        if Events.SUSPICIOUS_NUM.search(content):
            log.debug("Skipping possible time phrase with suspicious number: %s", content)
            return False

        if Events.TIME_INTENT_NEGATIVE.search(content):
            log.debug("Skipping time phrase with retrospective language: %s", content)
            return False

        if Events.CLOCK_TIME.search(content):
            return True

        if Events.RELATIVE_TIME.search(content):
            return bool(Events.TIME_INTENT_POSITIVE.search(content))

        if not Events.TIME_ANCHORS.search(content):
            log.debug("Message does not look like a time phrase: %s", content)
            return False

        return bool(Events.TIME_INTENT_POSITIVE.search(content))

    @commands.Cog.listener()
    async def on_command_error(self, ctx: commands.Context, error):
        original = getattr(error, "original", error)

        if isinstance(original, CommandNotFound):
            return
        if isinstance(original, TimeoutError):
            await ctx.message.reply("Connection timed out. Please try again later.")
        elif isinstance(original, TrustedUserRequired):
            await ctx.message.reply("You do not have permission to use that command.")
        elif isinstance(original, (UserNotInVoice, CheckFailure)):
            await ctx.message.reply("Please join a voice channel.")
        elif isinstance(original, AlreadyConnected):
            await ctx.message.reply("Sorry, I'm already connected elsewhere.")
        elif isinstance(original, AlreadyConnecting):
            await ctx.message.reply("Please wait until I've connected.")
        elif isinstance(original, (ConnectionNotReady, CannotCompleteAction)):
            await ctx.message.reply(
                "I am still not ready. Resubmit your request again later."
            )
        elif isinstance(original, ClientException):
            await ctx.message.reply(f"Something went wrong. Reason: {original}")
        else:
            full_error = "".join(traceback.format_exception(error))
            log.error(full_error)
            await ctx.send(
                f"```py\n{full_error[:1900]}```\n"
                f"**An exception has occurred!** This incident will be reported.\n"
            )

    @commands.Cog.listener()
    async def on_raw_reaction_add(self, payload: RawReactionActionEvent):
        if str(payload.emoji) != Events.COOKIE:
            return

        if payload.member is None:
            log.warning("Ignoring cookie update reaction without member context.")
            return

        channel = await self.client.fetch_channel(payload.channel_id)
        message = await channel.fetch_message(payload.message_id)
        ctx = await self.client.get_context(message)
        ctx.author = payload.member

        if not await is_trusted_user(ctx):
            return

        try:
            await message.attachments[0].save(config.COOKIES_FILE)
            await channel.send(f"Updated cookies to [this]({message.jump_url})!")
        except Exception as e:
            log.error("Failed to save uploaded cookies: %s", e, exc_info=True)
            await channel.send(
                "Failed to save uploaded cookies. Upload one text file attachment "
                f"and react with the cookie emoji. Reason: {e}"
            )

    @commands.Cog.listener()
    async def on_voice_state_update(
        self, member, before: discord.VoiceState, after: discord.VoiceState
    ):
        was_on_call = before.channel is not None and after.channel is None
        now_on_call = after.channel is not None and before.channel is None
        is_user_bot = lambda user: user is not None and user.id == self.client.user.id
        music_cog: Music = self.client.get_cog("Music")

        if not music_cog:
            return

        if was_on_call or now_on_call:
            channel = before.channel if was_on_call else after.channel

            if (
                was_on_call
                and len(channel.members) == 1
                and is_user_bot(channel.members[0])
            ):
                await music_cog.start_timeout_timer()

            if now_on_call and len(channel.members) == 1:
                wlcm_msg = await channel.send("Let me try joining in!")
                ctx = await self.client.get_context(wlcm_msg)
                await music_cog.join(ctx, channel, member)

            if was_on_call and is_user_bot(member):
                music_cog.reset()


async def setup(client):
    await client.add_cog(Events(client))
