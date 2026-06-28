import asyncio
import logging
from dataclasses import dataclass
from typing import Dict, Optional

import discord
from discord.ext import commands

from bot import config
from bot.core.checks import trusted_only
from bot.core.translation import (
    ArgosTranslateProvider,
    LanguagePair,
    TranslationCache,
    TranslationError,
    TranslationRequest,
    TranslationResult,
    TranslationService,
)


log = logging.getLogger(__name__)


@dataclass(frozen=True)
class TranslationChannelPair:
    source_channel_id: int
    mirror_channel_id: int
    source_lang: str
    mirror_lang: str

    def direction_for(self, channel_id: int) -> Optional[LanguagePair]:
        if channel_id == self.source_channel_id:
            return LanguagePair(self.source_lang, self.mirror_lang)
        if channel_id == self.mirror_channel_id:
            return LanguagePair(self.mirror_lang, self.source_lang)
        return None

    def target_channel_id_for(self, channel_id: int) -> Optional[int]:
        if channel_id == self.source_channel_id:
            return self.mirror_channel_id
        if channel_id == self.mirror_channel_id:
            return self.source_channel_id
        return None


@dataclass(frozen=True)
class MirroredMessage:
    source_message_id: int
    mirror_message_id: int
    source_channel_id: int
    mirror_channel_id: int
    pair: LanguagePair
    provider: str


class TranslationMirrorRegistry:
    def __init__(self):
        self.by_source_message_id: Dict[int, MirroredMessage] = {}
        self.by_mirror_message_id: Dict[int, MirroredMessage] = {}

    def add(self, mirrored_message: MirroredMessage) -> None:
        self.by_source_message_id[mirrored_message.source_message_id] = mirrored_message
        self.by_mirror_message_id[mirrored_message.mirror_message_id] = mirrored_message

    def contains_message(self, message_id: int) -> bool:
        return (
            message_id in self.by_source_message_id
            or message_id in self.by_mirror_message_id
        )


class Translation(commands.Cog):
    def __init__(self, client, service: TranslationService, channel_pairs):
        self.client = client
        self.service = service
        self.channel_pairs = channel_pairs
        self.registry = TranslationMirrorRegistry()
        self._locks = {
            (pair.source_channel_id, pair.mirror_channel_id): asyncio.Lock()
            for pair in channel_pairs
        }

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if self._should_ignore(message):
            return

        channel_pair = self._channel_pair_for(message.channel.id)
        if channel_pair is None:
            return

        language_pair = channel_pair.direction_for(message.channel.id)
        target_channel_id = channel_pair.target_channel_id_for(message.channel.id)
        if language_pair is None or target_channel_id is None:
            return

        lock = self._locks[
            (channel_pair.source_channel_id, channel_pair.mirror_channel_id)
        ]
        async with lock:
            await self._mirror_message(message, language_pair, target_channel_id)

    @commands.group(name="translation", invoke_without_command=True)
    @trusted_only
    async def translation_status(self, ctx):
        await ctx.send(
            "Translation mirroring is enabled for "
            f"{len(self.channel_pairs)} channel pair(s) using "
            f"{config.TRANSLATION_PROVIDER}."
        )

    async def _mirror_message(
        self,
        message: discord.Message,
        language_pair: LanguagePair,
        target_channel_id: int,
    ) -> None:
        try:
            target_channel = self.client.get_channel(target_channel_id)
            if target_channel is None:
                target_channel = await self.client.fetch_channel(target_channel_id)

            result = await self.service.translate(
                TranslationRequest(
                    text=message.content,
                    pair=language_pair,
                    context={
                        "message_id": message.id,
                        "channel_id": message.channel.id,
                        "author_id": message.author.id,
                    },
                )
            )
        except TranslationError:
            log.warning("Failed to translate message %s.", message.id, exc_info=True)
            return
        except discord.DiscordException:
            log.warning(
                "Failed to resolve translation target channel %s.",
                target_channel_id,
                exc_info=True,
            )
            return

        try:
            mirrored_message = await target_channel.send(
                self._format_mirror_message(message, result),
                allowed_mentions=discord.AllowedMentions.none(),
            )
        except discord.DiscordException:
            log.warning(
                "Failed to mirror translated message %s into channel %s.",
                message.id,
                target_channel_id,
                exc_info=True,
            )
            return
        self.registry.add(
            MirroredMessage(
                source_message_id=message.id,
                mirror_message_id=mirrored_message.id,
                source_channel_id=message.channel.id,
                mirror_channel_id=target_channel_id,
                pair=language_pair,
                provider=result.provider,
            )
        )

    def _should_ignore(self, message: discord.Message) -> bool:
        if (
            not message.content
            or len(message.content) > config.TRANSLATION_MAX_MESSAGE_LENGTH
        ):
            return True
        if message.author.bot:
            return True
        return self.registry.contains_message(message.id)

    def _channel_pair_for(self, channel_id: int) -> Optional[TranslationChannelPair]:
        for channel_pair in self.channel_pairs:
            if channel_pair.direction_for(channel_id) is not None:
                return channel_pair
        return None

    def _format_mirror_message(
        self,
        message: discord.Message,
        result: TranslationResult,
    ) -> str:
        author = discord.utils.escape_markdown(message.author.display_name)
        translated_text = result.translated_text.strip()
        body = (
            f"**{author}** [{result.pair.source}->{result.pair.target}]\n"
            f"{translated_text}"
        )

        if len(body) <= 2000:
            return body

        return f"{body[:1996]}..."


def build_translation_service(channel_pairs) -> TranslationService:
    language_pairs = []
    for channel_pair in channel_pairs:
        language_pairs.append(
            LanguagePair(channel_pair.source_lang, channel_pair.mirror_lang)
        )
        language_pairs.append(
            LanguagePair(channel_pair.mirror_lang, channel_pair.source_lang)
        )

    if config.TRANSLATION_PROVIDER != "argos":
        raise ValueError(
            f"Unsupported translation provider: {config.TRANSLATION_PROVIDER}"
        )

    return TranslationService(
        [ArgosTranslateProvider(language_pairs)],
        cache=TranslationCache(max_size=config.TRANSLATION_CACHE_SIZE),
        max_concurrency=config.TRANSLATION_MAX_CONCURRENCY,
    )


async def setup(client):
    channel_pairs = [
        TranslationChannelPair(**item)
        for item in config.parse_translation_channel_pairs()
    ]
    service = build_translation_service(channel_pairs)
    await client.add_cog(Translation(client, service, channel_pairs))
