import array
import asyncio
import json
import logging
import random
import time
from collections import defaultdict, namedtuple

import audioop
import discord
import numpy as np
import pyttsx3
import speech_recognition as sr
import yaml
from discord.ext import commands, voice_recv
from discord.ext.commands import Context
from resampy.core import resample

from bot import config
from bot.core.assistant import (
    AssistantController,
    IntentParserChain,
    OpenRouterIntentParser,
    RuleBasedIntentParser,
)
from bot.core.assistant.wake import OpenWakeWordDetector

log = logging.getLogger(__name__)


class Assistant(commands.Cog):
    Utterance = namedtuple("Utterance", ["content", "after", "quiet_after"])

    def __init__(self, client):
        self.client = client
        self.dialogs = self.load_dialogs()
        self.intents = self.load_intents()
        self.recognizer = sr.Recognizer()
        self.controller = AssistantController(client)
        self.parser = self.build_parser()

        self.enabled = False
        self.always_awake = False
        self._ctx: Context = None
        self._voice_client: discord.VoiceClient = None
        self._priority_speaker = None
        self._services_available = True

        self._loop = asyncio.get_event_loop()
        self._message_queue = asyncio.Queue()
        self._msg_queue_task = None

        self._turn_active = False
        self._transcription_user_id = None
        self._query_future = None
        self._stream_data = defaultdict(
            lambda: {"stopper": None, "buffer": array.array("B")}
        )

        self._resampled_stream = []
        self._wake_word = None
        self._tts_engine = None

        self._init_wake_word()
        self._init_tts()

    @commands.command()
    async def intents(self, ctx):
        await ctx.send(f"```{json.dumps(self.intents, indent=2)}```")

    @staticmethod
    def load_intents():
        with open(config.ASSISTANT_CONTEXT) as stream:
            return yaml.safe_load(stream)

    @staticmethod
    def load_dialogs():
        with open(config.ASSISTANT_DIALOGS) as fp:
            return json.load(fp)

    @staticmethod
    def build_parser():
        parsers = [RuleBasedIntentParser()]
        if config.ASSISTANT_LLM_PROVIDER == "openrouter":
            parsers.append(
                OpenRouterIntentParser(
                    api_key=config.ASSISTANT_OPENROUTER_API_KEY,
                    model=config.ASSISTANT_OPENROUTER_MODEL,
                    timeout_seconds=config.ASSISTANT_LLM_TIMEOUT_SECONDS,
                )
            )
        elif config.ASSISTANT_LLM_PROVIDER not in {"", "none"}:
            log.warning(
                "Unsupported ASSISTANT_LLM_PROVIDER=%s. Falling back to rules only.",
                config.ASSISTANT_LLM_PROVIDER,
            )

        return IntentParserChain(
            parsers,
            min_confidence=config.ASSISTANT_LLM_MIN_CONFIDENCE,
        )

    def _init_wake_word(self):
        try:
            self._wake_word = OpenWakeWordDetector(
                models=config.ASSISTANT_WAKEWORD_MODELS,
                threshold=config.ASSISTANT_WAKEWORD_THRESHOLD,
            )
        except Exception as exc:
            self._services_available = False
            log.error("Wake word services will not be available: %s", exc, exc_info=True)

    def _init_tts(self):
        try:
            self._tts_engine = pyttsx3.init()
            voices = self._tts_engine.getProperty("voices")
            if len(voices) > 1:
                self._tts_engine.setProperty("voice", voices[1].id)
        except Exception:
            self._tts_engine = None
            self._services_available = False
            log.error("Text-to-speech services will not be available.", exc_info=True)

    def enable(self, ctx: Context):
        if not self._services_available:
            log.info("Assistant cannot be enabled because a required service is unavailable.")
            return False

        if self.enabled:
            log.info("Assistant is already enabled.")
            return False

        self.enabled = True
        self._ctx = ctx
        self._voice_client = ctx.voice_client
        self._priority_speaker = ctx.author
        self._msg_queue_task = self.client.loop.create_task(self._process_message_queue())
        self._apply_sink(ctx)
        log.info("Enabled assistant.")
        return True

    def disable(self, ctx: Context = None):
        if not self.enabled:
            return

        self.enabled = False
        self._ctx = ctx or self._ctx

        voice_client = getattr(self._ctx, "voice_client", None) if self._ctx else None
        if voice_client:
            try:
                voice_client.stop_listening()
            except Exception:
                log.debug("Voice client was not listening.", exc_info=True)

        self.cleanup()
        log.info("Disabled assistant.")

    def restore(self, ctx: Context):
        if self.enabled:
            self._apply_sink(ctx)

    def cleanup(self):
        if self._msg_queue_task:
            self._msg_queue_task.cancel()
            self._msg_queue_task = None

        if self._query_future and not self._query_future.done():
            self._query_future.cancel()

        self._stop_transcription()
        self._release_music_suspension()
        while not self._message_queue.empty():
            self._message_queue.get_nowait()
            self._message_queue.task_done()
        self._resampled_stream = []
        self._turn_active = False

    def cog_unload(self):
        self.disable()
        if self._wake_word:
            self._wake_word.close()

    def _apply_sink(self, ctx: Context):
        def callback(user: discord.User, data: voice_recv.VoiceData):
            if not self.enabled or user is None or self._priority_speaker is None:
                return
            if user.id != self._priority_speaker.id:
                return

            if self._transcription_user_id == user.id:
                self._buffer_transcription_audio(user, data)
                return

            self._process_wake_audio(user, data)

        assistant_sink = voice_recv.SilenceGeneratorSink(voice_recv.BasicSink(callback))
        ctx.voice_client.listen(assistant_sink)

    def _process_wake_audio(self, user: discord.User, data: voice_recv.VoiceData):
        values = np.frombuffer(data.pcm, dtype=np.int16)
        value_matrix = np.array((values[::2], values[1::2]))
        resampled_values = resample(value_matrix, 48_000, 16_000).astype(np.int16)

        self._resampled_stream.extend(resampled_values[0])
        if len(self._resampled_stream) < 512:
            return

        audio_frame = self._resampled_stream[:512]
        self._resampled_stream = self._resampled_stream[512:]

        if self.always_awake:
            self._loop.call_soon_threadsafe(self._schedule_turn, user)
            return

        if self._wake_word.process(audio_frame):
            log.info("Detected wake word from %s.", user.display_name)
            self._resampled_stream = []
            self._loop.call_soon_threadsafe(self._schedule_turn, user)

    def _schedule_turn(self, user: discord.User):
        if self._turn_active:
            return

        self._turn_active = True
        prompt = random.choice(self.dialogs["prompts"]["general"])
        self.say(
            f"Hi {user.display_name}. {prompt}",
            quiet_after=True,
            after=lambda: self.client.loop.create_task(self._capture_and_handle(user)),
        )

    async def _capture_and_handle(self, user: discord.User):
        try:
            self._begin_transcription(user)

            try:
                text = await asyncio.wait_for(
                    self._query_future,
                    timeout=config.ASSISTANT_TRANSCRIPTION_TIMEOUT_SECONDS,
                )
            except asyncio.TimeoutError:
                log.info("Assistant transcription timed out.")
                self._release_music_suspension()
                self.say("I did not catch that.", quiet_after=False)
                return
            finally:
                self._stop_transcription()

            self._release_music_suspension()
            text = (text or "").strip()
            if not text:
                self.say("I did not catch that.", quiet_after=False)
                return

            log.info('%s said "%s".', user.display_name, text)
            intent = await self.parser.parse(text)
            log.info(
                "Assistant intent: action=%s confidence=%.2f source=%s query=%r.",
                intent.action.value,
                intent.confidence,
                intent.source,
                intent.query,
            )

            result = await self.controller.execute(self._ctx, intent)
            if result.speak and result.message:
                self.say(result.message, quiet_after=False)
        except Exception:
            log.warning("Assistant turn failed.", exc_info=True)
            self._release_music_suspension()
            self.say("Something went wrong.", quiet_after=False)
        finally:
            self._turn_active = False

    def _begin_transcription(self, user: discord.User):
        self._query_future = self.client.loop.create_future()
        self._stream_data[user.id] = {
            "stopper": None,
            "buffer": array.array("B"),
        }
        self._transcription_user_id = user.id

    def _stop_transcription(self):
        user_id = self._transcription_user_id
        self._transcription_user_id = None

        if user_id is None:
            return

        stopper = self._stream_data[user_id].get("stopper")
        if stopper:
            try:
                stopper(False)
            except Exception:
                log.debug("Failed to stop background transcription listener.", exc_info=True)

        self._stream_data[user_id] = {
            "stopper": None,
            "buffer": array.array("B"),
        }

    def _buffer_transcription_audio(self, user: discord.User, data: voice_recv.VoiceData):
        sdata = self._stream_data[user.id]
        sdata["buffer"].extend(data.pcm)

        if sdata["stopper"]:
            return

        sdata["stopper"] = self.recognizer.listen_in_background(
            DiscordSRAudioSource(sdata["buffer"]),
            self._get_bg_listener_callback(user),
            phrase_time_limit=8,
        )

    def _get_bg_listener_callback(self, user: discord.User):
        def callback(recognizer: sr.Recognizer, audio: sr.AudioData):
            text = ""
            try:
                with open(config.ASSISTANT_INCOMING_AUDIO, "wb") as fp:
                    fp.write(audio.get_wav_data())

                text = recognizer.recognize_whisper(
                    audio,
                    model="small",
                    language="english",
                )
            except Exception:
                log.warning("Failed to transcribe assistant utterance.", exc_info=True)

            def complete_future():
                if self._query_future and not self._query_future.done():
                    self._query_future.set_result(text)

            self._loop.call_soon_threadsafe(complete_future)

        return callback

    def say(self, message, quiet_after=False, after=None):
        utterance = Assistant.Utterance(message, after, quiet_after)
        self._loop.call_soon_threadsafe(self._enqueue_utterance, utterance)

    def _enqueue_utterance(self, utterance):
        self._message_queue.put_nowait(utterance)

    async def _process_message_queue(self):
        while True:
            utterance: Assistant.Utterance = await self._message_queue.get()
            try:
                await self._play_utterance(utterance)
            finally:
                self._message_queue.task_done()

    async def _play_utterance(self, utterance):
        if not self._ctx or not self._voice_client:
            log.warning("Dropping assistant utterance because voice context is unavailable.")
            return

        music = self.client.get_cog("Music")
        if music:
            try:
                await music.suspend(self._ctx)
            except Exception:
                log.debug("Could not suspend music playback before assistant speech.", exc_info=True)

        audio = await self.get_audio_from_text(utterance.content)
        await self._ctx.send(utterance.content)

        done = self.client.loop.create_future()

        def after_playback(error):
            if error:
                log.warning("Assistant utterance playback failed: %s", error)
            self.client.loop.call_soon_threadsafe(self._finish_playback_future, done, error)

        self._voice_client.play(audio, after=after_playback)
        await done

        if utterance.after:
            utterance.after()

        if not utterance.quiet_after:
            self._release_music_suspension()

    async def get_audio_from_text(self, message):
        if not self._tts_engine:
            raise RuntimeError("Text-to-speech service is unavailable.")

        await asyncio.to_thread(self._save_tts_audio, message)
        return await discord.FFmpegOpusAudio.from_probe(config.ASSISTANT_REPLY_AUDIO)

    def _save_tts_audio(self, message):
        self._tts_engine.save_to_file(message, str(config.ASSISTANT_REPLY_AUDIO))
        self._tts_engine.runAndWait()

    def _release_music_suspension(self):
        music = self.client.get_cog("Music")
        if not music:
            return

        try:
            music.remove_suspension()
        except Exception:
            log.debug("Could not release music suspension.", exc_info=True)

    @staticmethod
    def _finish_playback_future(future, result):
        if not future.done():
            future.set_result(result)


class DiscordSRAudioSource(sr.AudioSource):
    little_endian = True
    SAMPLE_RATE = 48_000
    SAMPLE_WIDTH = 2
    CHANNELS = 2
    CHUNK = 960

    def __init__(self, buffer: array.array):
        self.buffer = buffer
        self._entered = False

    @property
    def stream(self):
        return self

    def __enter__(self):
        if self._entered:
            log.warning("Already entered speech-recognition audio source.")
        self._entered = True
        return self

    def __exit__(self, *exc) -> None:
        self._entered = False
        if any(exc):
            log.exception("Error closing speech-recognition audio source.")

    def read(self, size: int) -> bytes:
        for _ in range(10):
            if len(self.buffer) < size * self.CHANNELS:
                time.sleep(0.1)
            else:
                break
        else:
            if len(self.buffer) == 0:
                return b""

        chunksize = size * self.CHANNELS
        audiochunk = self.buffer[:chunksize].tobytes()
        del self.buffer[: min(chunksize, len(audiochunk))]
        return audioop.tomono(audiochunk, self.SAMPLE_WIDTH, 1, 1)

    def close(self) -> None:
        self.buffer.clear()


async def setup(client):
    await client.add_cog(Assistant(client))
