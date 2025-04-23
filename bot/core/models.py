from dataclasses import dataclass
from enum import Enum

from discord.ext.commands import Context
from discord import User, Message


class Source(Enum):
    CMD = "COMMMAND"
    WEB = "WEBPLAYR"


@dataclass
class MusicRequest:
    query: str
    author: User
    ctx: Context = None
    source: Source = None
    msg: Message = None


@dataclass
class Song:
    title: str
    duration: str
    requester: User
    ie_result: dict
    auto_play: bool = False
    url: str = None
    thumbnail: str = None
    webpage: str = None
    start_at: int = 0
