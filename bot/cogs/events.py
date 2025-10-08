import os
import re
import logging
import discord
import traceback
import parsedatetime as pdt

from asyncio import TimeoutError
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
from datetime import datetime

from discord.ext import commands
from discord import RawReactionActionEvent, Message, MessageType
from discord.ext.commands.errors import CommandNotFound, CheckFailure
from discord.errors import ClientException
from tzlocal import get_localzone

from bot import EMBED_COLOR_THEME, BOT_SPAM_CHANNEL
from bot.cogs.music import Music
from bot.core.exceptions import (
    AlreadyConnected,
    AlreadyConnecting,
    UserNotInVoice,
    CannotCompleteAction,
    ConnectionNotReady,
)

log = logging.getLogger(__name__)


class Events(commands.Cog):
    # EMOJIS
    COOKIE = "🍪"

    AUTO_PING_THRESHOLD = 2
    AUTO_PING_MAX_INTEVAL = 5

    TIMEZONES = [
        "Asia/Kolkata",
        "Australia/Sydney",
        "Europe/London",
        "America/Toronto",
        "America/Los_Angeles",
    ]

    def __init__(self, client):
        self.client = client

        # --TRACE MOE--
        self.message = None
        self.matches = None
        self.index = 0

        self._last_message = None
        self._repetitions = 0

        self.calendar = pdt.Calendar()

        # Load all stickers
        stickers_path = "bot/resources/stickers"
        self.stickers = {}
        for file in os.listdir(stickers_path):
            name = file.split(".")[0]
            self.stickers[name] = stickers_path + "/" + file

    @commands.Cog.listener()
    async def on_message(self, message: Message):
        # Ignore messages sent by the bot
        if message.author.id == self.client.user.id:
            return

        util_base = self.client.get_cog("Utils")
        if util_base.is_pinging and util_base.ping_who.get(message.author, 0) > 0:
            util_base.ping_who[message.author] = 0
            await util_base.channel.send("You're back!")

        wordle_base = self.client.get_cog("Wordle")
        await wordle_base.guess(message.content, message.author)

        # Automatic trigger for ping utility
        if (
            self._last_message
            and len(message.mentions) > 0
            and set(self._last_message.mentions) == set(message.mentions)
            and message.type == MessageType.default
            and (message.created_at - self._last_message.created_at).total_seconds()
            < Events.AUTO_PING_MAX_INTEVAL
        ):
            self._repetitions += 1

            if self._repetitions >= Events.AUTO_PING_THRESHOLD:
                await util_base.ping(message.channel, message.mentions, 25)
                self._repetitions = 0
        else:
            self._repetitions = 0

        # Sticker utility
        for name, path in self.stickers.items():
            if re.search(rf"\b{name}\b", message.content, re.IGNORECASE):
                sticker_file = discord.File(fp=path)
                await message.channel.send(file=sticker_file)

        # Timezone utility
        local_tz = None
        for role in message.author.roles:
            try:
                local_tz = ZoneInfo(role.name)
                break
            except ZoneInfoNotFoundError:
                print(f"Couldn't detect timezone from {role}")
                pass

        if local_tz:
            local_base_time = datetime.now().astimezone(local_tz)
            timestamp, status = self.calendar.parseDT(message.content, local_base_time)
            timestamp = timestamp.replace(tzinfo=local_tz)
            if status > 1:
                conv_timestamps = {
                    tz: timestamp.astimezone(ZoneInfo(tz)).strftime("%H:%M")
                    for tz in Events.TIMEZONES
                }

                await message.reply(
                    "\n".join([f"{ts} ({tz})" for tz, ts in conv_timestamps.items()])
                )

        self._last_message = message

    @commands.Cog.listener()
    async def on_command_error(self, ctx: commands.Context, error):
        # Get original error
        original = getattr(error, "original", error)

        if isinstance(original, CommandNotFound):
            return  # Ignore CommandNotFound errors
        elif isinstance(original, TimeoutError):
            await ctx.message.reply("❗\tConnection timed out. Please try again later.")
        elif isinstance(original, (UserNotInVoice, CheckFailure)):
            await ctx.message.reply("⚠️\tPlease join a voice channel.")
        elif isinstance(original, AlreadyConnected):
            await ctx.message.reply("😔\tSorry, I'm already connected elsewhere.")
        elif isinstance(original, AlreadyConnecting):
            await ctx.message.reply("🛑\tPlease **WAIT** until I've connected.")
        elif isinstance(original, (ConnectionNotReady, CannotCompleteAction)):
            await ctx.message.reply(
                "⚠️\tI am still not yet ready. Resubmit your request again later."
            )
        elif isinstance(original, ClientException):
            await ctx.message.reply(f"❗\tSomething went wrong. Reason: {original}")
        else:
            full_error = "".join(traceback.format_exception(error))
            log.error(full_error)
            await ctx.send(
                f"```py\n{full_error[:1900]}```\n"
                f"**An exception has occurred!** This incident will be reported.\n"
            )

    @commands.Cog.listener()
    async def on_raw_reaction_add(self, payload: RawReactionActionEvent):
        # For updating cookies
        if str(payload.emoji) == Events.COOKIE:
            channel = await self.client.fetch_channel(payload.channel_id)
            message = await channel.fetch_message(payload.message_id)

            try:
                await message.attachments[0].save("bot/secrets/cookies.txt")
                await channel.send(f"Updated cookies to [this]({message.jump_url})!")
            except Exception as e:
                log.error(f"Failed to save uploaded cookies: {e}")
                await channel.send(
                    f"Failed to save uploaded cookies. You must upload it as a single text file attachment and add a reaction with the cookie emoji: {e}"
                )

    @commands.Cog.listener()
    async def on_voice_state_update(
        self, member, before: discord.VoiceState, after: discord.VoiceState
    ):
        # Initialize some basic flags
        was_on_call = before.channel is not None and after.channel is None
        now_on_call = after.channel is not None and before.channel is None
        is_user_bot = lambda member: member != None and member.id == self.client.user.id
        music_cog: Music = self.client.get_cog("Music")

        if was_on_call or now_on_call:
            # Handling events where a member left or joined a call
            channel = before.channel if was_on_call else after.channel

            if (
                was_on_call
                and len(channel.members) == 1
                and is_user_bot(channel.members[0])
            ):
                await music_cog.start_timeout_timer()

            if now_on_call and len(channel.members) == 1:
                # Join the call automatically when someone is in the voice channel
                # The Music cog needs a command context in order to run normally.
                # As a workaround, we will use the bot to send a message and use
                # that context instead.
                # The only difference is that we must specify the voice channel
                # and the author explicitly. Everything else works the same.

                wlcm_msg = await channel.send("Let me try joining in!")
                ctx = await self.client.get_context(wlcm_msg)
                await music_cog.join(ctx, channel, member)

            if was_on_call and is_user_bot(member):
                music_cog.reset()
        else:
            # Handling events where a member transferred between calls
            pass


async def setup(client):
    await client.add_cog(Events(client))
