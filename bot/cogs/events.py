import logging
import traceback
from asyncio import TimeoutError

from discord import Message, RawReactionActionEvent
from discord.errors import ClientException
from discord.ext import commands
from discord.ext.commands.errors import CheckFailure, CommandNotFound

from bot.core.checks import TrustedUserRequired
from bot.core.exceptions import (
    AlreadyConnected,
    AlreadyConnecting,
    CannotCompleteAction,
    ConnectionNotReady,
    UserNotInVoice,
)
from bot.core.message_features import (
    CookieUpdater,
    PingAutomation,
    StickerResponder,
    TimezoneResponder,
    VoiceAutoJoin,
)

log = logging.getLogger(__name__)


class Events(commands.Cog):
    def __init__(self, client):
        self.client = client
        self.ping_automation = PingAutomation(client)
        self.sticker_responder = StickerResponder()
        self.timezone_responder = TimezoneResponder()
        self.cookie_updater = CookieUpdater(client)
        self.voice_auto_join = VoiceAutoJoin(client)

    @commands.Cog.listener()
    async def on_message(self, message: Message):
        if message.author.id == self.client.user.id:
            return

        await self.ping_automation.handle_message(message)

        wordle_base = self.client.get_cog("Wordle")
        if wordle_base:
            await wordle_base.guess(message.content, message.author)

        await self.sticker_responder.handle_message(message)
        await self.timezone_responder.handle_message(message)

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
        await self.cookie_updater.handle_reaction(payload)

    @commands.Cog.listener()
    async def on_voice_state_update(self, member, before, after):
        await self.voice_auto_join.handle_voice_state_update(member, before, after)


async def setup(client):
    await client.add_cog(Events(client))
