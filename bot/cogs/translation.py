import asyncio
import logging
import re
import time
from dataclasses import dataclass
from typing import Dict, Optional

import discord
from discord import app_commands
from discord.ext import commands

from bot import config
from bot.core.checks import trusted_only
from bot.core.translation import (
    ArgosTranslateProvider,
    GeminiTranslateProvider,
    LanguagePair,
    SlangAwareTranslationProvider,
    TranslationCache,
    TranslationError,
    TranslationProviderRouter,
    TranslationRequest,
    TranslationResult,
    TranslationService,
    SQLiteTranslationCache,
)
from bot.core.translation_settings import (
    GuildTranslationSettings,
    TranslationSettingsStore,
    direction_key,
)
from bot.core.writing_feedback import (
    GeminiWritingRewriteProvider,
    GrammalecteWritingFeedbackProvider,
    WritingFeedbackError,
    WritingFeedbackRequest,
    WritingFeedbackResult,
    WritingFeedbackService,
)

log = logging.getLogger(__name__)
MAX_WRITING_CONTEXT_CHARS = 240
MIRROR_WEBHOOK_NAME = "Bard Translation Mirror"
TRANSLATION_RATE_LIMIT_NOTICE = (
    "-# Some translations were skipped because the translation provider was "
    "rate-limited."
)
URL_RE = re.compile(r"https?://\S+|www\.\S+", re.IGNORECASE)
CUSTOM_EMOJI_RE = re.compile(r"<a?:[A-Za-z0-9_]+:\d+>")
MENTION_RE = re.compile(r"<[@#@&]!?&?\d+>|<[@#@&]?\d+>")
FEEDBACK_REACTION = "📝"
REWRITE_REACTION = "✨"


@dataclass(frozen=True)
class TranslationChannelPair:
    source_channel_id: int
    mirror_channel_id: int
    source_lang: str
    mirror_lang: str
    guild_id: Optional[int] = None

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
    def __init__(
        self,
        client,
        service: TranslationService,
        channel_pairs,
        writing_feedback_service: Optional[WritingFeedbackService] = None,
        guild_settings: Optional[Dict[int, GuildTranslationSettings]] = None,
    ):
        self.client = client
        self.service = service
        self.writing_feedback_service = writing_feedback_service
        self.channel_pairs = []
        self.guild_settings = {}
        self.registry = TranslationMirrorRegistry()
        self._webhooks: Dict[int, discord.Webhook] = {}
        self._webhook_unavailable_channel_ids = set()
        self._background_tasks = set()
        self._batch_queues = {}
        self._batch_workers = {}
        self._rate_limit_notice_until = {}
        self._locks = {}
        self._set_translation_state(channel_pairs, guild_settings or {})
        self.feedback_context_menu = None
        self.rewrite_context_menu = None
        if getattr(self.client, "tree", None) is not None:
            self.feedback_context_menu = app_commands.ContextMenu(
                name="French Feedback",
                callback=self.feedback_context_menu_callback,
            )
            self.client.tree.add_command(self.feedback_context_menu)
            self.rewrite_context_menu = app_commands.ContextMenu(
                name="French Rewrite",
                callback=self.rewrite_context_menu_callback,
            )
            self.client.tree.add_command(self.rewrite_context_menu)

    def cog_unload(self):
        for task in self._background_tasks:
            task.cancel()
        for task in self._batch_workers.values():
            task.cancel()
        for command in (self.feedback_context_menu, self.rewrite_context_menu):
            if command is None:
                continue
            self.client.tree.remove_command(command.name, type=command.type)

    async def reload_settings(self) -> None:
        guild_settings = load_guild_translation_settings(self.client.guilds)
        channel_pairs = channel_pairs_from_guild_settings(guild_settings)
        service = build_translation_service(channel_pairs, guild_settings)
        await service.warmup()
        self.service = service
        self.writing_feedback_service = build_writing_feedback_service()
        self._set_translation_state(channel_pairs, guild_settings)

    def _set_translation_state(self, channel_pairs, guild_settings):
        for task in self._batch_workers.values():
            task.cancel()
        self._batch_workers = {}
        self._batch_queues = {}
        self.channel_pairs = list(channel_pairs)
        self.guild_settings = guild_settings or {}
        self._locks = {
            (pair.source_channel_id, pair.mirror_channel_id): asyncio.Lock()
            for pair in self.channel_pairs
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
        if self._translation_batching_enabled(channel_pair, language_pair):
            self._enqueue_translation_message(
                message,
                channel_pair,
                language_pair,
                target_channel_id,
            )
            return

        async with lock:
            await self._mirror_message(message, language_pair, target_channel_id)
            if self._automatic_writing_feedback_enabled(channel_pair):
                self._schedule_writing_feedback(
                    message,
                    channel_pair,
                    language_pair,
                )

    def _enqueue_translation_message(
        self,
        message: discord.Message,
        channel_pair: TranslationChannelPair,
        language_pair: LanguagePair,
        target_channel_id: int,
    ) -> None:
        pair_key = (channel_pair.source_channel_id, channel_pair.mirror_channel_id)
        queue = self._batch_queues.get(pair_key)
        if queue is None:
            queue = asyncio.Queue()
            self._batch_queues[pair_key] = queue

        queue.put_nowait((message, channel_pair, language_pair, target_channel_id))

        worker = self._batch_workers.get(pair_key)
        if worker is None or worker.done():
            worker = asyncio.create_task(self._translation_batch_worker(pair_key, queue))
            self._batch_workers[pair_key] = worker
            worker.add_done_callback(self._log_background_task_failure)

    async def _translation_batch_worker(self, pair_key, queue) -> None:
        while True:
            first_item = await queue.get()
            batch = [first_item]
            await asyncio.sleep(max(0, config.TRANSLATION_GEMINI_BATCH_WINDOW_MS) / 1000)

            max_size = max(1, config.TRANSLATION_GEMINI_BATCH_MAX_SIZE)
            while len(batch) < max_size:
                try:
                    batch.append(queue.get_nowait())
                except asyncio.QueueEmpty:
                    break

            lock = self._locks[pair_key]
            async with lock:
                await self._mirror_message_batch(batch)

            for _ in batch:
                queue.task_done()

    async def _mirror_message_batch(self, batch) -> None:
        if len(batch) == 1:
            message, channel_pair, language_pair, target_channel_id = batch[0]
            await self._mirror_message(message, language_pair, target_channel_id)
            if self._automatic_writing_feedback_enabled(channel_pair):
                self._schedule_writing_feedback(message, channel_pair, language_pair)
            return

        translatable_batch = []
        for item in batch:
            message, channel_pair, language_pair, target_channel_id = item
            if (
                config.TRANSLATION_SKIP_LOW_VALUE_MESSAGES
                and self._is_low_value_translation_message(message.content)
            ):
                await self._send_translation_result(
                    message,
                    language_pair,
                    target_channel_id,
                    self._passthrough_translation_result(message, language_pair),
                )
                continue
            translatable_batch.append(item)

        if not translatable_batch:
            return

        requests = [
            TranslationRequest(
                text=message.content,
                pair=language_pair,
                context={
                    "guild_id": getattr(getattr(message, "guild", None), "id", None),
                    "message_id": message.id,
                    "channel_id": message.channel.id,
                    "author_id": message.author.id,
                },
            )
            for message, channel_pair, language_pair, target_channel_id in translatable_batch
        ]

        try:
            results = await self.service.translate_many(tuple(requests))
        except TranslationError as exc:
            if self._is_translation_rate_limited(exc):
                noticed_channels = set()
                for message, channel_pair, language_pair, target_channel_id in translatable_batch:
                    if target_channel_id in noticed_channels:
                        continue
                    noticed_channels.add(target_channel_id)
                    await self._send_rate_limit_notice(target_channel_id)
            log.warning(
                "Failed to batch translate %s messages.",
                len(translatable_batch),
                exc_info=True,
            )
            for message, channel_pair, language_pair, target_channel_id in translatable_batch:
                await self._mirror_message(message, language_pair, target_channel_id)
                if self._automatic_writing_feedback_enabled(channel_pair):
                    self._schedule_writing_feedback(
                        message,
                        channel_pair,
                        language_pair,
                    )
            return

        for (message, channel_pair, language_pair, target_channel_id), result in zip(
            translatable_batch,
            results,
        ):
            await self._send_translation_result(
                message,
                language_pair,
                target_channel_id,
                result,
            )
            if self._automatic_writing_feedback_enabled(channel_pair):
                self._schedule_writing_feedback(message, channel_pair, language_pair)

    def _schedule_writing_feedback(
        self,
        message: discord.Message,
        channel_pair: TranslationChannelPair,
        language_pair: LanguagePair,
    ) -> None:
        task = asyncio.create_task(
            self._send_writing_feedback(message, channel_pair, language_pair)
        )
        self._background_tasks.add(task)
        task.add_done_callback(self._background_tasks.discard)
        task.add_done_callback(self._log_background_task_failure)

    @staticmethod
    def _log_background_task_failure(task) -> None:
        if task.cancelled():
            return
        try:
            task.result()
        except Exception:
            log.warning("Background translation task failed.", exc_info=True)

    async def feedback_context_menu_callback(
        self,
        interaction: discord.Interaction,
        message: discord.Message,
    ):
        await self._send_context_feedback(
            interaction,
            message,
            force_rewrite=False,
        )

    async def rewrite_context_menu_callback(
        self,
        interaction: discord.Interaction,
        message: discord.Message,
    ):
        await self._send_context_feedback(
            interaction,
            message,
            force_rewrite=True,
        )

    async def _send_context_feedback(
        self,
        interaction: discord.Interaction,
        message: discord.Message,
        *,
        force_rewrite: bool = False,
    ):
        if self.writing_feedback_service is None:
            await interaction.response.send_message(
                "Writing feedback is not enabled.",
                ephemeral=True,
            )
            return

        language = self._feedback_language_for(message)
        if language is None:
            await interaction.response.send_message(
                "Feedback is only available for human messages in the mirror channel.",
                ephemeral=True,
            )
            return

        ephemeral = not force_rewrite
        await interaction.response.defer(ephemeral=ephemeral, thinking=True)
        result = await self._assess_writing_message(
            message,
            language,
            force_rewrite=force_rewrite,
        )
        if result is None:
            await interaction.followup.send(
                "I could not assess that message.",
                ephemeral=True,
            )
            return

        await interaction.followup.send(
            self._format_writing_feedback(message, result),
            ephemeral=ephemeral,
            wait=True,
        )

    @commands.Cog.listener()
    async def on_raw_reaction_add(self, payload: discord.RawReactionActionEvent):
        if self.client.user is not None and payload.user_id == self.client.user.id:
            return
        if str(payload.emoji) not in {FEEDBACK_REACTION, REWRITE_REACTION}:
            return
        if self.writing_feedback_service is None:
            return

        channel = self.client.get_channel(payload.channel_id)
        if channel is None:
            try:
                channel = await self.client.fetch_channel(payload.channel_id)
            except discord.DiscordException:
                log.debug("Failed to fetch reaction channel.", exc_info=True)
                return

        try:
            message = await channel.fetch_message(payload.message_id)
        except discord.DiscordException:
            log.debug("Failed to fetch reaction message.", exc_info=True)
            return

        language = self._feedback_language_for(message)
        if language is None:
            return

        force_rewrite = str(payload.emoji) == REWRITE_REACTION
        result = await self._assess_writing_message(
            message,
            language,
            force_rewrite=force_rewrite,
        )
        if result is None:
            return

        try:
            await channel.send(
                self._format_writing_feedback(message, result),
                reference=message,
                mention_author=False,
                allowed_mentions=discord.AllowedMentions.none(),
            )
        except discord.DiscordException:
            log.warning(
                "Failed to send reaction-triggered writing feedback for message %s.",
                message.id,
                exc_info=True,
            )

    @commands.group(name="translation", invoke_without_command=True)
    @trusted_only
    async def translation_status(self, ctx):
        await ctx.send(
            "Translation mirroring is enabled for "
            f"{len(self.channel_pairs)} configured channel pair(s)."
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

            if (
                config.TRANSLATION_SKIP_LOW_VALUE_MESSAGES
                and self._is_low_value_translation_message(message.content)
            ):
                result = self._passthrough_translation_result(message, language_pair)
                await self._send_translation_result(
                    message,
                    language_pair,
                    target_channel_id,
                    result,
                    target_channel=target_channel,
                )
                return

            result = await self.service.translate(
                TranslationRequest(
                    text=message.content,
                    pair=language_pair,
                    context={
                        "guild_id": getattr(getattr(message, "guild", None), "id", None),
                        "message_id": message.id,
                        "channel_id": message.channel.id,
                        "author_id": message.author.id,
                    },
                )
            )
        except TranslationError as exc:
            if self._is_translation_rate_limited(exc):
                await self._send_rate_limit_notice(target_channel_id)
            log.warning("Failed to translate message %s.", message.id, exc_info=True)
            return
        except discord.DiscordException:
            log.warning(
                "Failed to resolve translation target channel %s.",
                target_channel_id,
                exc_info=True,
            )
            return

        await self._send_translation_result(
            message,
            language_pair,
            target_channel_id,
            result,
            target_channel=target_channel,
        )

    @staticmethod
    def _passthrough_translation_result(
        message: discord.Message,
        language_pair: LanguagePair,
    ) -> TranslationResult:
        return TranslationResult(
            translated_text=message.content,
            provider="passthrough",
            source_text=message.content,
            pair=language_pair,
        )

    async def _send_rate_limit_notice(self, target_channel_id: int) -> None:
        now = time.monotonic()
        if now < self._rate_limit_notice_until.get(target_channel_id, 0):
            return

        self._rate_limit_notice_until[target_channel_id] = (
            now + max(1.0, config.TRANSLATION_GEMINI_RATE_LIMIT_COOLDOWN_SECONDS)
        )

        try:
            target_channel = self.client.get_channel(target_channel_id)
            if target_channel is None:
                target_channel = await self.client.fetch_channel(target_channel_id)
            await target_channel.send(
                TRANSLATION_RATE_LIMIT_NOTICE,
                allowed_mentions=discord.AllowedMentions.none(),
            )
        except discord.DiscordException:
            log.warning(
                "Failed to send translation rate-limit notice to channel %s.",
                target_channel_id,
                exc_info=True,
            )

    @staticmethod
    def _is_translation_rate_limited(error: BaseException) -> bool:
        text = str(error).casefold()
        return "429" in text or "rate-limit" in text or "cooldown" in text

    async def _send_translation_result(
        self,
        message: discord.Message,
        language_pair: LanguagePair,
        target_channel_id: int,
        result: TranslationResult,
        *,
        target_channel=None,
    ) -> None:
        try:
            if target_channel is None:
                target_channel = self.client.get_channel(target_channel_id)
                if target_channel is None:
                    target_channel = await self.client.fetch_channel(target_channel_id)
            mirrored_message = await self._send_mirrored_message(
                target_channel,
                message,
                result,
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

    async def _send_mirrored_message(
        self,
        target_channel,
        source_message: discord.Message,
        result: TranslationResult,
    ):
        if config.TRANSLATION_USE_WEBHOOKS:
            try:
                webhook = await self._webhook_for_channel(target_channel)
                if webhook is not None:
                    return await webhook.send(
                        self._format_webhook_mirror_message(source_message, result),
                        username=self._webhook_username(source_message),
                        avatar_url=self._webhook_avatar_url(source_message),
                        allowed_mentions=discord.AllowedMentions.none(),
                        wait=True,
                    )
            except (discord.DiscordException, AttributeError):
                self._webhook_unavailable_channel_ids.add(target_channel.id)
                log.warning(
                    "Failed to mirror message through webhook in channel %s; "
                    "falling back to bot message.",
                    target_channel.id,
                    exc_info=True,
                )

        return await target_channel.send(
            self._format_mirror_message(source_message, result),
            allowed_mentions=discord.AllowedMentions.none(),
        )

    async def _webhook_for_channel(self, channel):
        if channel.id in self._webhook_unavailable_channel_ids:
            return None

        cached = self._webhooks.get(channel.id)
        if cached is not None:
            return cached

        webhooks = await channel.webhooks()
        webhook = discord.utils.get(webhooks, name=MIRROR_WEBHOOK_NAME)
        if webhook is None:
            webhook = await channel.create_webhook(
                name=MIRROR_WEBHOOK_NAME,
                reason="Bard translation mirroring",
            )

        self._webhooks[channel.id] = webhook
        return webhook

    async def _send_writing_feedback(
        self,
        message: discord.Message,
        channel_pair: TranslationChannelPair,
        language_pair: LanguagePair,
    ) -> None:
        if self.writing_feedback_service is None:
            return
        if message.channel.id != channel_pair.mirror_channel_id:
            return
        if language_pair.source.casefold() not in config.WRITING_FEEDBACK_LANGUAGES:
            return

        try:
            result = await self._assess_writing_message(
                message,
                language_pair.source,
                auto=True,
            )
        except WritingFeedbackError:
            log.warning(
                "Failed to check writing feedback for message %s.",
                message.id,
                exc_info=True,
            )
            return

        if result is None:
            return

        try:
            await message.channel.send(
                self._format_writing_feedback(message, result),
                reference=message,
                mention_author=False,
                allowed_mentions=discord.AllowedMentions.none(),
            )
        except discord.DiscordException:
            log.warning(
                "Failed to send writing feedback for message %s.",
                message.id,
                exc_info=True,
            )

    async def _assess_writing_message(
        self,
        message: discord.Message,
        language: str,
        *,
        auto: bool = False,
        force_rewrite: bool = False,
    ) -> Optional[WritingFeedbackResult]:
        request = WritingFeedbackRequest(
            text=message.content,
            language=language,
            context={
                "guild_id": getattr(getattr(message, "guild", None), "id", None),
                "message_id": message.id,
                "channel_id": message.channel.id,
                "author_id": message.author.id,
                "conversation_context": await self._writing_context_for(message),
                "auto_rewrite_enabled": self._auto_rewrite_enabled_for(message),
                "auto_rewrite_threshold": self._auto_rewrite_threshold_for(message),
                "llm_extra_instructions": self._llm_extra_instructions_for(message),
            },
        )
        if auto:
            return await self.writing_feedback_service.check(request)
        return await self.writing_feedback_service.assess(
            request,
            force_rewrite=force_rewrite,
        )

    def _feedback_language_for(self, message: discord.Message) -> Optional[str]:
        if not getattr(message, "content", None):
            return None
        if getattr(message.author, "bot", False):
            return None
        if getattr(message, "webhook_id", None):
            return None

        channel_pair = self._channel_pair_for(message.channel.id)
        if channel_pair is None:
            return None
        if message.channel.id != channel_pair.mirror_channel_id:
            return None

        language_pair = channel_pair.direction_for(message.channel.id)
        if language_pair is None:
            return None
        if language_pair.source.casefold() not in config.WRITING_FEEDBACK_LANGUAGES:
            return None
        return language_pair.source

    def _should_ignore(self, message: discord.Message) -> bool:
        if (
            not message.content
            or len(message.content) > config.TRANSLATION_MAX_MESSAGE_LENGTH
        ):
            return True
        if message.author.bot:
            return True
        return self.registry.contains_message(message.id)

    @staticmethod
    def _is_low_value_translation_message(content: str) -> bool:
        text = content.strip()
        if not text:
            return True

        text = URL_RE.sub("", text)
        text = CUSTOM_EMOJI_RE.sub("", text)
        text = MENTION_RE.sub("", text)
        text = re.sub(r"\s+", "", text)
        if not text:
            return True

        return not any(character.isalnum() for character in text)

    def _channel_pair_for(self, channel_id: int) -> Optional[TranslationChannelPair]:
        for channel_pair in self.channel_pairs:
            if channel_pair.direction_for(channel_id) is not None:
                return channel_pair
        return None

    def _settings_for_message(self, message: discord.Message):
        guild_id = getattr(getattr(message, "guild", None), "id", None)
        if guild_id is None:
            return None
        return self.guild_settings.get(int(guild_id))

    def _automatic_writing_feedback_enabled(
        self,
        channel_pair: TranslationChannelPair,
    ) -> bool:
        if channel_pair.guild_id is None:
            return False
        settings = self.guild_settings.get(channel_pair.guild_id)
        if settings is None:
            return False
        return settings.auto_rewrite_enabled

    def _translation_batching_enabled(
        self,
        channel_pair: TranslationChannelPair,
        language_pair: LanguagePair,
    ) -> bool:
        if not config.TRANSLATION_GEMINI_BATCH_ENABLED:
            return False
        if channel_pair.guild_id is None:
            return False
        settings = self.guild_settings.get(channel_pair.guild_id)
        if settings is None:
            return False
        return settings.provider_for(language_pair.source, language_pair.target) == "gemini"

    def _auto_rewrite_threshold_for(self, message: discord.Message) -> Optional[int]:
        settings = self._settings_for_message(message)
        if settings is None:
            return None
        return settings.auto_rewrite_threshold

    def _auto_rewrite_enabled_for(self, message: discord.Message) -> bool:
        settings = self._settings_for_message(message)
        if settings is None:
            return True
        return settings.auto_rewrite_enabled

    def _llm_extra_instructions_for(self, message: discord.Message) -> str:
        settings = self._settings_for_message(message)
        if settings is None:
            return ""
        return settings.llm_extra_instructions

    async def _writing_context_for(self, message: discord.Message):
        context = []

        replied_message = await self._reply_context_message(message)
        if self._should_use_context_message(replied_message, current_message=message):
            context.append(self._format_context_message(replied_message))

        previous_message = await self._previous_human_message(message)
        if self._should_use_context_message(
            previous_message,
            current_message=message,
        ):
            if previous_message.id != getattr(replied_message, "id", None):
                context.append(self._format_context_message(previous_message))

        return tuple(item for item in context if item)

    async def _reply_context_message(self, message: discord.Message):
        reference = getattr(message, "reference", None)
        if reference is None:
            return None
        resolved = getattr(reference, "resolved", None)
        if getattr(resolved, "content", None):
            return resolved

        message_id = getattr(reference, "message_id", None)
        channel_id = getattr(reference, "channel_id", None)
        if not message_id or channel_id != message.channel.id:
            return None

        try:
            return await message.channel.fetch_message(message_id)
        except discord.DiscordException:
            log.debug(
                "Failed to fetch replied-to writing feedback context message.",
                exc_info=True,
            )
            return None

    async def _previous_human_message(self, message: discord.Message):
        try:
            async for candidate in message.channel.history(
                limit=5,
                before=message,
                oldest_first=False,
            ):
                if self._should_use_context_message(candidate, current_message=message):
                    return candidate
        except discord.DiscordException:
            log.debug(
                "Failed to fetch previous writing feedback context message.",
                exc_info=True,
            )
        return None

    def _should_use_context_message(
        self,
        candidate,
        *,
        current_message: discord.Message,
    ) -> bool:
        if candidate is None:
            return False
        if getattr(candidate, "id", None) == current_message.id:
            return False
        if not getattr(candidate, "content", None):
            return False
        author = getattr(candidate, "author", None)
        if getattr(author, "bot", False):
            return False
        return not self.registry.contains_message(candidate.id)

    @staticmethod
    def _format_context_message(message: discord.Message) -> str:
        author = discord.utils.escape_markdown(message.author.display_name)
        content = " ".join(message.content.split())
        if len(content) > MAX_WRITING_CONTEXT_CHARS:
            content = f"{content[: MAX_WRITING_CONTEXT_CHARS - 3]}..."
        return f"{author}: {content}"

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

    @staticmethod
    def _format_webhook_mirror_message(
        message: discord.Message,
        result: TranslationResult,
    ) -> str:
        translated_text = result.translated_text.strip()
        source_url = getattr(message, "jump_url", None)
        if not source_url:
            if len(translated_text) <= 2000:
                return translated_text
            return f"{translated_text[:1996]}..."

        source_link = f"\n-# [View original]({source_url})"
        max_text_length = max(1, 2000 - len(source_link) - 3)
        if len(translated_text) > max_text_length:
            translated_text = f"{translated_text[:max_text_length]}..."
        return f"{translated_text}{source_link}"

    @staticmethod
    def _webhook_username(message: discord.Message) -> str:
        display_name = getattr(message.author, "display_name", "") or "Unknown"
        username = " ".join(display_name.split())
        return username[:80] or "Unknown"

    @staticmethod
    def _webhook_avatar_url(message: discord.Message) -> Optional[str]:
        avatar = getattr(message.author, "display_avatar", None)
        url = getattr(avatar, "url", None)
        return str(url) if url else None

    def _format_writing_feedback(
        self,
        message: discord.Message,
        result: WritingFeedbackResult,
    ) -> str:
        if result.llm_rewrite:
            return self._format_writing_rewrite(message, result)

        author = discord.utils.escape_markdown(message.author.display_name)
        lines = [f"**{author}** French writing score: {result.score}/100"]

        for issue in result.issues[: config.WRITING_FEEDBACK_MAX_ISSUES]:
            suggestion = ""
            if issue.suggestions:
                suggestion = f" Suggestion: {issue.suggestions[0]}"
            lines.append(f"- {issue.message}{suggestion}")

        if result.recommendation:
            lines.append(f"Recommended: {result.recommendation}")

        body = "\n".join(lines)
        if len(body) <= 2000:
            return body

        return f"{body[:1996]}..."

    def _format_writing_rewrite(
        self,
        message: discord.Message,
        result: WritingFeedbackResult,
    ) -> str:
        lines = [
            "Original:",
            result.source_text.strip(),
            "",
            "Natural rewrite:",
            result.recommendation.strip() if result.recommendation else "",
        ]

        if result.rewrite_notes:
            lines.extend(["", "Notes:"])
            lines.extend(f"- {note}" for note in result.rewrite_notes)

        body = "\n".join(line for line in lines if line is not None)
        if len(body) <= 2000:
            return body

        return f"{body[:1996]}..."


def build_translation_service(channel_pairs, guild_settings=None) -> TranslationService:
    language_pairs = []
    provider_routes = {}
    guild_settings = guild_settings or {}
    for channel_pair in channel_pairs:
        forward_pair = LanguagePair(channel_pair.source_lang, channel_pair.mirror_lang)
        reverse_pair = LanguagePair(channel_pair.mirror_lang, channel_pair.source_lang)
        language_pairs.append(forward_pair)
        language_pairs.append(reverse_pair)

        if channel_pair.guild_id is not None:
            settings = guild_settings.get(channel_pair.guild_id)
            if settings is not None:
                provider_routes[
                    (
                        channel_pair.guild_id,
                        forward_pair.source,
                        forward_pair.target,
                    )
                ] = settings.provider_for(
                    forward_pair.source,
                    forward_pair.target,
                    "",
                )
                provider_routes[
                    (
                        channel_pair.guild_id,
                        reverse_pair.source,
                        reverse_pair.target,
                    )
                ] = settings.provider_for(
                    reverse_pair.source,
                    reverse_pair.target,
                    "",
                )

    providers = []
    argos_pairs = []
    gemini_pairs = []
    for pair in language_pairs:
        provider_names = {
            provider_name
            for (guild_id, source, target), provider_name in provider_routes.items()
            if source.casefold() == pair.source.casefold()
            and target.casefold() == pair.target.casefold()
        }

        for provider_name in provider_names:
            if provider_name == "argos":
                argos_pairs.append(pair)
            elif provider_name == "gemini":
                gemini_pairs.append(pair)
            else:
                raise ValueError(
                    f"Unsupported translation provider for "
                    f"{pair.source}->{pair.target}: {provider_name}"
                )

    dedupe_pairs = lambda pairs: list(
        {  # noqa: E731
            (pair.source.casefold(), pair.target.casefold()): pair for pair in pairs
        }.values()
    )
    argos_pairs = dedupe_pairs(argos_pairs)
    gemini_pairs = dedupe_pairs(gemini_pairs)

    if argos_pairs:
        providers.append(ArgosTranslateProvider(argos_pairs))
    if gemini_pairs:
        providers.append(
            GeminiTranslateProvider(
                gemini_pairs,
                api_key=config.WRITING_FEEDBACK_GEMINI_API_KEY,
                model=config.WRITING_FEEDBACK_GEMINI_MODEL,
                timeout_seconds=config.WRITING_FEEDBACK_LLM_TIMEOUT_SECONDS,
                rate_limit_cooldown_seconds=(
                    config.TRANSLATION_GEMINI_RATE_LIMIT_COOLDOWN_SECONDS
                ),
            )
        )

    provider = TranslationProviderRouter(providers, routes=provider_routes)
    if config.TRANSLATION_NORMALIZE_SLANG:
        provider = SlangAwareTranslationProvider(provider)

    return TranslationService(
        [provider],
        cache=build_translation_cache(),
        max_concurrency=config.TRANSLATION_MAX_CONCURRENCY,
    )


def build_translation_cache():
    if (
        config.TRANSLATION_PERSISTENT_CACHE_ENABLED
        and config.TRANSLATION_CACHE_SIZE > 0
    ):
        return SQLiteTranslationCache(
            config.TRANSLATION_CACHE_FILE,
            max_size=config.TRANSLATION_CACHE_SIZE,
        )
    return TranslationCache(max_size=config.TRANSLATION_CACHE_SIZE)


def build_writing_feedback_service() -> Optional[WritingFeedbackService]:
    if not config.WRITING_FEEDBACK_ENABLED:
        return None

    if config.WRITING_FEEDBACK_PROVIDER != "grammalecte":
        raise ValueError(
            f"Unsupported writing feedback provider: {config.WRITING_FEEDBACK_PROVIDER}"
        )

    rewrite_provider = build_writing_rewrite_provider()
    return WritingFeedbackService(
        [GrammalecteWritingFeedbackProvider(config.WRITING_FEEDBACK_LANGUAGES)],
        rewrite_provider=rewrite_provider,
        score_threshold=config.WRITING_FEEDBACK_SCORE_THRESHOLD,
        recommend_threshold=config.WRITING_FEEDBACK_RECOMMEND_THRESHOLD,
    )


def build_writing_rewrite_provider():
    if config.WRITING_FEEDBACK_LLM_PROVIDER == "none":
        return None

    if config.WRITING_FEEDBACK_LLM_PROVIDER != "gemini":
        raise ValueError(
            "Unsupported writing feedback LLM provider: "
            f"{config.WRITING_FEEDBACK_LLM_PROVIDER}"
        )

    return GeminiWritingRewriteProvider(
        api_key=config.WRITING_FEEDBACK_GEMINI_API_KEY,
        model=config.WRITING_FEEDBACK_GEMINI_MODEL,
        timeout_seconds=config.WRITING_FEEDBACK_LLM_TIMEOUT_SECONDS,
        rate_limit_cooldown_seconds=(
            config.WRITING_FEEDBACK_LLM_RATE_LIMIT_COOLDOWN_SECONDS
        ),
    )


async def setup(client):
    guild_settings = load_guild_translation_settings(client.guilds)
    channel_pairs = channel_pairs_from_guild_settings(guild_settings)
    service = build_translation_service(channel_pairs, guild_settings)
    await service.warmup()
    writing_feedback_service = build_writing_feedback_service()
    await client.add_cog(
        Translation(
            client,
            service,
            channel_pairs,
            writing_feedback_service,
            guild_settings,
        )
    )


def load_guild_translation_settings(guilds):
    store = TranslationSettingsStore(config.TRANSLATION_GUILD_SETTINGS_FILE)
    return store.load_all()


def channel_pairs_from_guild_settings(guild_settings):
    pairs = []
    for settings in guild_settings.values():
        if not settings.configured:
            continue
        pairs.append(
            TranslationChannelPair(
                guild_id=settings.guild_id,
                source_channel_id=settings.source_channel_id,
                mirror_channel_id=settings.mirror_channel_id,
                source_lang=settings.source_lang,
                mirror_lang=settings.mirror_lang,
            )
        )
    return pairs
