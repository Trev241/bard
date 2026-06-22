import logging

import discord
from discord.ext import commands

from bot.core.yordle import ChampionProvider, YordleGame

log = logging.getLogger(__name__)


class Wordle(commands.Cog):
    def __init__(self, client, champion_provider=None):
        self.client = client
        self.champion_provider = champion_provider or ChampionProvider()
        self.word_bank = self.champion_provider.load()
        self.game = YordleGame(self.word_bank)
        self.ctx = None

        if self.word_bank == self.champion_provider.fallback:
            log.warning("Using fallback Yordle champion bank.")

    @commands.command()
    async def yordle(self, ctx):
        self.ctx = ctx
        try:
            image_path = self.game.start()
        except ValueError as exc:
            await ctx.send(f"Yordle is unavailable: {exc}")
            return

        await ctx.send(file=discord.File(fp=image_path))

    async def guess(self, guess: str, author):
        image_path, solved = self.game.guess(guess)
        if not image_path:
            return

        await self.ctx.send(file=discord.File(fp=image_path))
        if solved:
            await self.ctx.send(f"{author.display_name} guessed the name!")


async def setup(client):
    await client.add_cog(Wordle(client))
