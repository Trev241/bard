import logging

import yt_dlp

from bot import config


def youtube_logger():
    logger = logging.getLogger("yt-dlp")
    logger.setLevel(logging.DEBUG)

    if not any(getattr(handler, "_bard_ytdlp", False) for handler in logger.handlers):
        handler = logging.StreamHandler()
        handler._bard_ytdlp = True
        logger.addHandler(handler)

    return logger


def ytdlp_options():
    return {
        "format": "bestaudio",
        "cookiefile": str(config.COOKIES_FILE),
        "verbose": False,
        "quiet": False,
        "logger": youtube_logger(),
    }


def flat_ytdlp_options():
    return {
        "extract_flat": True,
        "quiet": True,
    }


def create_ytdlp(flat=False):
    options = flat_ytdlp_options() if flat else ytdlp_options()
    return yt_dlp.YoutubeDL(options)

