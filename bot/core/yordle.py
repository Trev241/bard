from random import choice

import requests
from PIL import Image, ImageDraw, ImageFont

from bot import config


DEFAULT_CHAMPIONS = [
    "AATROX",
    "AHRI",
    "AKALI",
    "ANNIE",
    "ASHE",
    "GAREN",
    "LUX",
    "RYZE",
    "SIVIR",
    "TEEMO",
]


class ChampionProvider:
    VERSION_URL = "https://ddragon.leagueoflegends.com/realms/euw.json"
    CHAMPION_DATA_URL = "https://ddragon.leagueoflegends.com/cdn/{version}/data/en_US/champion.json"

    def __init__(self, session=None, fallback=None, timeout=10):
        self.session = session or requests.Session()
        self.fallback = fallback or DEFAULT_CHAMPIONS
        self.timeout = timeout

    def fetch(self):
        version_response = self.session.get(self.VERSION_URL, timeout=self.timeout)
        version_response.raise_for_status()
        version = version_response.json()["v"]

        champion_response = self.session.get(
            self.CHAMPION_DATA_URL.format(version=version),
            timeout=self.timeout,
        )
        champion_response.raise_for_status()
        data = champion_response.json()["data"]
        return [champion.upper() for champion in data.keys()]

    def load(self):
        try:
            return self.fetch()
        except Exception:
            return list(self.fallback)


class YordleGame:
    LETTER_SIZE = 50

    def __init__(
        self,
        word_bank,
        image_path=config.YORDLE_IMAGE,
        font_path=config.DROID_MONO_FONT,
    ):
        self.word_bank = [word.upper() for word in word_bank]
        self.image_path = image_path
        self.font_path = font_path
        self.running = False
        self.word = None
        self.last_guess = None

    @property
    def size(self):
        return len(self.word) if self.word else 0

    def start(self):
        if not self.word_bank:
            raise ValueError("Yordle cannot start without a word bank.")

        self.running = True
        self.word = choice(self.word_bank)
        self.last_guess = "?" * self.size
        return self.render()

    def guess(self, guess):
        normalized = guess.upper()
        if (
            not self.running
            or len(normalized) != self.size
            or normalized not in self.word_bank
        ):
            return None, False

        self.last_guess = normalized
        image_path = self.render()
        solved = normalized == self.word
        if solved:
            self.running = False

        return image_path, solved

    def render(self):
        padding = 5
        image = Image.new(
            mode="RGBA",
            size=(self.LETTER_SIZE * self.size, self.LETTER_SIZE),
            color=(0, 0, 0, 0),
        )
        font = ImageFont.truetype(self.font_path, 45)
        draw = ImageDraw.Draw(image)

        letters = {}
        for char in self.word:
            letters[char] = letters.get(char, 0) + 1

        position = [5, 0]
        for index, char in enumerate(self.last_guess):
            if letters.get(char, 0):
                letters[char] -= 1
                bg = "green" if char == self.word[index] else "orange"
                fg = "white"
            else:
                bg = (0, 0, 0, 0)
                fg = (180, 180, 180, 200)

            left, top, right, bottom = draw.textbbox(position, char, font=font)
            draw.rectangle(
                (left - padding, top - padding, right + padding, bottom + padding),
                fill=bg,
            )
            draw.text(position, char, font=font, fill=fg)
            position[0] += self.LETTER_SIZE

        image.save(self.image_path)
        return self.image_path

