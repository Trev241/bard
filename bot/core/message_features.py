import logging
import re
from datetime import datetime
from zoneinfo import ZoneInfo

import discord
import parsedatetime as pdt
from discord import Message, MessageType, RawReactionActionEvent

from bot import config
from bot.core.checks import is_trusted_user
from bot.core.timezones import resolve_timezone

logger = logging.getLogger(__name__)


class PingAutomation:
    AUTO_PING_THRESHOLD = 2
    AUTO_PING_MAX_INTERVAL = 5

    def __init__(self, client):
        self.client = client
        self._last_message = None
        self._repetitions = 0

    async def handle_message(self, message: Message):
        util_base = self.client.get_cog("Utils")
        if not util_base:
            self._last_message = message
            return

        if util_base.is_pinging and util_base.ping_who.get(message.author, 0) > 0:
            util_base.ping_who[message.author] = 0
            await util_base.channel.send("You're back!")

        if (
            self._last_message
            and len(message.mentions) > 0
            and set(self._last_message.mentions) == set(message.mentions)
            and message.type == MessageType.default
            and (message.created_at - self._last_message.created_at).total_seconds()
            < self.AUTO_PING_MAX_INTERVAL
        ):
            self._repetitions += 1
            if self._repetitions >= self.AUTO_PING_THRESHOLD:
                ctx = await self.client.get_context(message)
                if await is_trusted_user(ctx):
                    await util_base.ping(message.channel, message.mentions, 25)
                self._repetitions = 0
        else:
            self._repetitions = 0

        self._last_message = message


class StickerResponder:
    def __init__(self, stickers_dir=config.STICKERS_DIR):
        self.stickers = {
            path.stem: path
            for path in stickers_dir.iterdir()
            if path.is_file()
        }

    async def handle_message(self, message: Message):
        for name, path in self.stickers.items():
            if re.search(rf"\b{re.escape(name)}\b", message.content, re.IGNORECASE):
                await message.channel.send(file=discord.File(fp=path))


class TimezoneResponder:
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

    def __init__(self, calendar=None):
        self.calendar = calendar or pdt.Calendar()

    async def handle_message(self, message: Message):
        local_tz = self.resolve_author_timezone(message.author)
        if not local_tz:
            logger.debug("No timezone role found for %s.", message.author)
            return

        timestamp = self.parse_time_reference(message.content, local_tz)
        if not timestamp:
            return

        view = discord.ui.View()
        view.add_item(self.build_timezone_select(timestamp))
        await message.reply(view=view)

    def resolve_author_timezone(self, author):
        for role in getattr(author, "roles", []):
            local_tz = resolve_timezone(role.name)
            if local_tz:
                return local_tz

        return None

    def build_timezone_select(self, timestamp):
        select = discord.ui.Select(placeholder="Check other timezones with Chronokeeper")
        for tz in self.TIMEZONES:
            ts = timestamp.astimezone(ZoneInfo(tz))
            ts_str = ts.strftime("%H:%M - %a, %b %d ")
            is_day = 8 <= ts.hour < 20
            select.add_option(
                label=ts_str,
                description=ZoneInfo(tz).key,
                emoji="\u2600\ufe0f" if is_day else "\U0001f319",
            )

        async def callback(interaction: discord.Interaction):
            await interaction.response.defer()

        select.callback = callback
        return select

    def parse_time_reference(self, content, local_tz):
        if not self.should_attempt_timezone_conversion(content):
            return None

        local_base_time = datetime.now().astimezone(local_tz)
        timestamp, status = self.calendar.parseDT(content, local_base_time)
        if status <= 1:
            logger.debug("parsedatetime did not find a usable time in: %s", content)
            return None

        return timestamp.replace(tzinfo=local_tz)

    @classmethod
    def should_attempt_timezone_conversion(cls, content):
        if cls.SUSPICIOUS_NUM.search(content):
            logger.debug("Skipping possible time phrase with suspicious number: %s", content)
            return False

        if cls.TIME_INTENT_NEGATIVE.search(content):
            logger.debug("Skipping time phrase with retrospective language: %s", content)
            return False

        if cls.CLOCK_TIME.search(content):
            return True

        if cls.RELATIVE_TIME.search(content):
            return bool(cls.TIME_INTENT_POSITIVE.search(content))

        if not cls.TIME_ANCHORS.search(content):
            logger.debug("Message does not look like a time phrase: %s", content)
            return False

        return bool(cls.TIME_INTENT_POSITIVE.search(content))


class CookieUpdater:
    COOKIE = "\U0001f36a"

    def __init__(self, client):
        self.client = client

    async def handle_reaction(self, payload: RawReactionActionEvent):
        if str(payload.emoji) != self.COOKIE:
            return

        if payload.member is None:
            logger.warning("Ignoring cookie update reaction without member context.")
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
        except Exception as exc:
            logger.error("Failed to save uploaded cookies: %s", exc, exc_info=True)
            await channel.send(
                "Failed to save uploaded cookies. Upload one text file attachment "
                f"and react with the cookie emoji. Reason: {exc}"
            )


class VoiceAutoJoin:
    def __init__(self, client):
        self.client = client

    async def handle_voice_state_update(self, member, before, after):
        was_on_call = before.channel is not None and after.channel is None
        now_on_call = after.channel is not None and before.channel is None
        music_cog = self.client.get_cog("Music")
        if not music_cog or not (was_on_call or now_on_call):
            return

        channel = before.channel if was_on_call else after.channel

        if (
            was_on_call
            and len(channel.members) == 1
            and channel.members[0].id == self.client.user.id
        ):
            await music_cog.start_timeout_timer()

        if now_on_call and len(channel.members) == 1:
            welcome_msg = await channel.send("Let me try joining in!")
            ctx = await self.client.get_context(welcome_msg)
            await music_cog.join(ctx, channel, member)

        if was_on_call and member.id == self.client.user.id:
            music_cog.reset()

