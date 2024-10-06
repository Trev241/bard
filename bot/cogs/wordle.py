import discord
import requests
import logging

from random import randrange
from PIL import Image, ImageDraw, ImageFont
from discord.ext import commands

log = logging.getLogger()


class Wordle(commands.Cog):
    LETTER_SIZE = 50
    HIDDEN_WORD_IMAGE_FILENAME = "yordle_word.png"

    def __init__(self, client):
        self.client = client
        self.running = False
        self.ctx = None

        # Updating champion data
        try:
            # Fetch latest version
            version_url = "https://ddragon.leagueoflegends.com/realms/euw.json"
            version_data = requests.get(version_url).json()
            version = version_data["v"]

            # Fetch champion data
            champion_data_url = f"http://ddragon.leagueoflegends.com/cdn/{version}/data/en_US/champion.json"
            response = requests.get(champion_data_url).json()
            champion_data = response["data"]

            self.word_bank = [champion.upper() for champion in champion_data.keys()]
        except Exception as e:
            log.error(f"An error occured while trying to update champion data: {e}")

    @commands.command()
    async def yordle(self, ctx):
        self.running = True
        self.ctx = ctx
        self.word = self.word_bank[randrange(0, len(self.word_bank))]
        self.size = len(self.word)
        self.last_guess = "?" * self.size

        await self.display()

    async def display(self):
        self.image_for_hidden_word()
        file = discord.File(fp=Wordle.HIDDEN_WORD_IMAGE_FILENAME)
        await self.ctx.send(file=file)

    def image_for_hidden_word(self):
        padding = 5
        image = Image.new(
            mode="RGBA",
            size=(Wordle.LETTER_SIZE * self.size, Wordle.LETTER_SIZE),
            color=(0, 0, 0, 0),
        )
        font = ImageFont.truetype("./fonts/DroidSansMono.ttf", 45)
        draw = ImageDraw.Draw(image)

        letters = {}
        for c in self.word:
            letters[c] = letters.get(c, 0) + 1

        position = [5, 0]

        for i, c in enumerate(self.last_guess):
            if letters.get(c, 0):
                letters[c] -= 1
                bg = "green" if c == self.word[i] else "orange"
                fg = "white"
            else:
                bg = (0, 0, 0, 0)
                fg = (180, 180, 180, 200)

            left, top, right, bottom = draw.textbbox(position, c, font=font)
            draw.rectangle(
                (left - padding, top - padding, right + padding, bottom + padding),
                fill=bg,
            )
            draw.text(position, c, font=font, fill=fg)
            position[0] += Wordle.LETTER_SIZE

        image.save(Wordle.HIDDEN_WORD_IMAGE_FILENAME)

    async def guess(self, guess: str):
        guess = guess.upper()

        if self.running and len(guess) == self.size and guess in self.word_bank:
            self.last_guess = guess
            await self.display()

            if guess == self.word:
                await self.ctx.send(f"{self.ctx.author.display_name} guessed the name!")
                self.running = False


async def setup(client):
    await client.add_cog(Wordle(client))
