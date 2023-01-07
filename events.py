import requests
import urllib.parse

from discord.ext import commands
from discord import RawTypingEvent, Embed, RawReactionActionEvent
from bs4 import BeautifulSoup
from constants import EMBED_COLOR_THEME, NEXT_PAGE, PREV_PAGE, BOT_SPAM_CHANNEL

class Events(commands.Cog):
    def __init__(self, client):
        self.client = client

        self.message = None
        self.matches = None
        self.index = 0

    @commands.Cog.listener()
    async def on_message(self, message):
        url = None

        # For now, only processing the first attachment
        if len(message.attachments) > 0:
            attachment = message.attachments[0]
            # print(attachment.content_type)
            url = attachment.url if attachment.content_type[:5] == 'image' else None
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
            await self.message.add_reaction(PREV_PAGE)
            await self.message.add_reaction(NEXT_PAGE)

    @commands.Cog.listener()
    async def on_raw_reaction_add(self, payload: RawReactionActionEvent):
        if payload.user_id != self.client.user.id and payload.message_id == self.message.id:
            if str(payload.emoji) == NEXT_PAGE:
                self.index += 1
            elif str(payload.emoji) == PREV_PAGE:
                self.index -= 1

            # Remove the emoji added by the user
            await self.message.remove_reaction(str(payload.emoji), payload.member)

            # Clamp index
            self.index = min(max(0, self.index), len(self.matches) - 1)

            embed = self.describe_as_embed()
            await self.message.edit(embed=embed)

    def process(url):
        response = requests.get(
            f'https://api.trace.moe/search?url={urllib.parse.quote_plus(url)}'
        ).json()

        data = []

        for match in response['result']:
            anilist_page = f'https://anilist.co/anime/{match["anilist"]}'
            info = BeautifulSoup(requests.get(anilist_page).text, features='lxml')

            try:
                title = str(info.find('div', class_='header').find('h1').string).strip()
            except:
                title = '[Failed to scrape title]'

            data.append(
                {
                    'anilist_page': anilist_page,
                    'episode': match['episode'] if match['episode'] != None else 'NIL',
                    'title': title,
                    'video': match['video'],
                    'image': match['image'],
                    'similarity': '%.2f' % (match['similarity'] * 100)
                }
            )

        return data

    def describe_as_embed(self):
        match = self.matches[self.index]

        return Embed.from_dict({
            'title': f'{match["title"]} ({self.index + 1}/{len(self.matches)})',
            'description': f'Is this the anime you were talking about?',
            'fields': [
                {
                    'name': 'Episode',
                    'value': match['episode'],
                    'inline': True
                },
                {
                    'name': 'AniList',
                    'value': f'[Click here]({match["anilist_page"]})',
                    'inline': True
                },
                {
                    'name': 'Similarity',
                    'value': f'{match["similarity"]}%',
                    'inline': True
                }
            ],
            'image': {
                'url': match['image'],
            },
            'color': EMBED_COLOR_THEME
        })

    @commands.Cog.listener()
    async def on_raw_typing(self, payload: RawTypingEvent):
        util_base = self.client.get_cog('Utils')

        if util_base.is_pinging and util_base.who.id == payload.user_id:
            await util_base.ping_stop(util_base.ctx)
            await util_base.ctx.send('You\'re back!')

async def setup(client):
    await client.add_cog(Events(client))