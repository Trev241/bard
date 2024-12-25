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
    ctx: Context
    source: Source
    msg: Message = None
