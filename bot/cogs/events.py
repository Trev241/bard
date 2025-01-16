import discord.ext.commands
import requests
import urllib.parse
import logging
import discord
import traceback

from discord.ext import commands
from discord import Embed, RawReactionActionEvent, Message, MessageType
from bs4 import BeautifulSoup
from bot import EMBED_COLOR_THEME, BOT_SPAM_CHANNEL, socketio
import discord.ext

log = logging.getLogger(__name__)


class Events(commands.Cog):
    # EMOJIS
    NEXT_PAGE = "➡️"
    PREV_PAGE = "⬅️"
    COOKIE = "🍪"

    AUTO_PING_THRESHOLD = 2
    AUTO_PING_MAX_INTEVAL = 5

    def __init__(self, client):
        self.client = client

        # --TRACE MOE--
        self.message = None
        self.matches = None
        self.index = 0

        self._last_message = None
        self._repetitions = 0

    @commands.Cog.listener()
    async def on_message(self, message: Message):
        # Ignore messages sent by the bot
        if message.author.id == self.client.user.id:
            return

        # await self.find_anime(message)

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

        self._last_message = message

    @commands.Cog.listener()
    async def on_command_error(self, ctx, error: discord.DiscordException):
        full_error = traceback.format_exception(error)
        await ctx.send(
            f"**An exception has occurred!** (User {ctx.author.display_name} used "
            f"{ctx.command.qualified_name} with args {ctx.args})\n```py\n{''.join(full_error)}```"
        )

    async def find_anime(self, message: Message):
        """
        Searches for anime that contain the attachment (image) sent using the trace.moe API.
        """

        url = None

        # For now, only processing the first attachment
        if len(message.attachments) > 0:
            attachment = message.attachments[0]
            url = attachment.url if attachment.content_type[:5] == "image" else None
        else:
            try:
                requests.get(message.content).status_code == 200
                url = message.content
            except:
                pass

        if url:
            self.matches = Events.process(url)

            # Generate embed for first match
            self.index = 0
            embed = self.describe_as_embed()

            # Delete navigation emojis from old message
            if self.message:
                await self.message.clear_reactions()

            # Send and cache the message
            channel = await message.guild.fetch_channel(BOT_SPAM_CHANNEL)
            self.message = await channel.send(embed=embed)

            # Adding reactions preemptively for navigation
            await self.message.add_reaction(Events.PREV_PAGE)
            await self.message.add_reaction(Events.NEXT_PAGE)

    @commands.Cog.listener()
    async def on_raw_reaction_add(self, payload: RawReactionActionEvent):
        if (
            payload.user_id != self.client.user.id
            and self.message
            and payload.message_id == self.message.id
        ):
            # For handling page transitions
            if str(payload.emoji) == Events.NEXT_PAGE:
                self.index += 1
            elif str(payload.emoji) == Events.PREV_PAGE:
                self.index -= 1

            # Remove the emoji added by the user
            await self.message.remove_reaction(str(payload.emoji), payload.member)

            # Clamp index
            self.index = min(max(0, self.index), len(self.matches) - 1)

            embed = self.describe_as_embed()
            await self.message.edit(embed=embed)

        # For updating cookies
        if str(payload.emoji) == Events.COOKIE:
            channel = await self.client.fetch_channel(payload.channel_id)
            message = await channel.fetch_message(payload.message_id)

            try:
                await message.attachments[0].save("cookies.txt")
                await channel.send(f"Updated cookies to [this]({message.jump_url})!")
            except Exception as e:
                log.error(f"Failed to save uploaded cookies: {e}")
                await channel.send(
                    f"Failed to save uploaded cookies. You must upload it as a single text file attachment and add a reaction with the cookie emoji: {e}"
                )

    def process(url):
        """
        Sends an API request to trace.moe and processes the response before returning it.
        """

        response = requests.get(
            f"https://api.trace.moe/search?url={urllib.parse.quote_plus(url)}"
        ).json()

        data = []

        for match in response["result"]:
            anilist_page = f'https://anilist.co/anime/{match["anilist"]}'
            info = BeautifulSoup(requests.get(anilist_page).text, features="lxml")

            try:
                title = str(info.find("div", class_="header").find("h1").string).strip()
            except:
                title = "[Failed to scrape title]"

            data.append(
                {
                    "anilist_page": anilist_page,
                    "episode": match["episode"] if match["episode"] != None else "NIL",
                    "title": title,
                    "video": match["video"],
                    "image": match["image"],
                    "similarity": "%.2f" % (match["similarity"] * 100),
                }
            )

        return data

    def describe_as_embed(self):
        match = self.matches[self.index]

        return Embed.from_dict(
            {
                "title": f'{match["title"]} ({self.index + 1}/{len(self.matches)})',
                "description": f"Is this the anime you were talking about?",
                "fields": [
                    {"name": "Episode", "value": match["episode"], "inline": True},
                    {
                        "name": "AniList",
                        "value": f'[Click here]({match["anilist_page"]})',
                        "inline": True,
                    },
                    {
                        "name": "Similarity",
                        "value": f'{match["similarity"]}%',
                        "inline": True,
                    },
                ],
                "image": {
                    "url": match["image"],
                },
                "color": EMBED_COLOR_THEME,
            }
        )

    @commands.Cog.listener()
    async def on_voice_state_update(
        self, member, before: discord.VoiceState, after: discord.VoiceState
    ):
        # Initialize some basic flags
        was_on_call = before.channel is not None and after.channel is None
        now_on_call = after.channel is not None and before.channel is None
        is_user_bot = lambda member: member != None and member.id == self.client.user.id
        music_cog = self.client.get_cog("Music")

        if was_on_call or now_on_call:
            # Handling events where a member left or joined a call
            channel = before.channel if was_on_call else after.channel

            if (
                was_on_call
                and len(channel.members) == 1
                and is_user_bot(channel.members[0].id)
            ):
                await music_cog.start_timeout_timer()

            if now_on_call and len(channel.members) == 1:
                # Join the call automatically when someone is in the voice channel
                # The Music cog needs a command context in order to run normally.
                # As a workaround, we will use the bot to send a message and use
                # that context instead.
                # The only difference is that we must specify the voice channel
                # and the author explicitly. Everything else works the same.

                wlcm_msg = await channel.send("I'm here too!")
                ctx = await self.client.get_context(wlcm_msg)
                await music_cog.join_vc(ctx, channel, member)

            if was_on_call and is_user_bot(member.id):
                # Attempt to reset again in case the bot was forcefully disconnected
                music_cog.reset()
        else:
            # Handling events where a member transferred between calls
            pass


async def setup(client):
    await client.add_cog(Events(client))
