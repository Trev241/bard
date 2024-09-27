import os
import array
import time
import asyncio
import json
import random
import yaml
import platform

import numpy as np
import logging
import discord
import audioop

import pyttsx3
import pvporcupine
import pvrhino

# import assemblyai as aai
import speech_recognition as sr

from resampy.core import resample
from discord.ext import commands, voice_recv
from discord.ext.commands import Context
from collections import defaultdict, deque, namedtuple

log = logging.getLogger()


class Assistant(commands.Cog):
    Utterance = namedtuple("Utterance", ["content", "after", "quiet_after"])

    with open("assistant/Bard Assistant.yml") as stream:
        INTENTS = yaml.safe_load(stream)
    with open("assistant/dialogs.json") as fp:
        DIALOGS = json.load(fp)

    def __init__(self, client):
        # Bot state
        self.client = client
        self.recognizer = sr.Recognizer()
        self.enabled = False
        self.always_awake = False

        self._ctx = None
        self._is_awake = False
        self._query = None
        self._transcription_required = False
        self._services_available = True

        # Events
        self._events = {
            event_type: asyncio.Event()
            for event_type in [
                "UTTERANCE_REQUIRED",
                "INTENT_DETECTED",
                "QUERY_DETECTED",
                "UTTERANCE_FINISHED",
            ]
        }
        self._events["UTTERANCE_FINISHED"].set()

        self._loop = asyncio.get_event_loop()
        self._voice_client: discord.VoiceClient = None
        self._resampled_stream = []
        self._stream_data = defaultdict(
            lambda: {"stopper": None, "buffer": array.array("B")}
        )

        # Porcupine wake-word
        self._priority_speaker = None
        porcupine_mdl = (
            "Okay-Bard_en_linux_v3_0_0.ppn"
            if platform.system() == "Linux"
            else "Okay-Bard_en_windows_v3_0_0.ppn"
        )

        try:
            self.porcupine = pvporcupine.create(
                access_key=os.getenv("PV_ACCESS_KEY"),
                keyword_paths=[f"assistant/{porcupine_mdl}"],
                # keywords=["picovoice", "bumblebee"],
                # sensitivities=[1.0, 1.0],
            )
        except Exception as e:
            self._services_available = False
            log.error(
                f"Failed to launch porcupine service. It is possible that the service has exceeded its usage for this month: {e}"
            )
            log.error("Wake word services will not be available!")

        # TTS
        self._tts_engine = pyttsx3.init()
        tts_voice_id = self._tts_engine.getProperty("voices")[1].id
        self._tts_engine.setProperty("voice", tts_voice_id)
        self._message_queue = deque()
        self._msg_queue_task = None

        # Rhino speech-to-intent
        self._intent_queue = deque()
        self._loop.create_task(self._process_intent())
        rhino_mdl = (
            "Bard-Assistant_en_linux_v3_0_0.rhn"
            if platform.system() == "Linux"
            else "Bard-Assistant_en_windows_v3_0_0.rhn"
        )

        try:
            self.rhino = pvrhino.create(
                access_key=os.getenv("PV_ACCESS_KEY"),
                context_path=f"assistant/{rhino_mdl}",
                # require_endpoint=False,  # Rhino will not require an chunk of silence at the end
            )
        except Exception as e:
            self._services_available = False
            log.error(
                f"Failed to launch rhino service. It is possible that the service has exceeded its usage for this month: {e}"
            )
            log.error("Intent intepretation services will not be available!")

        # AssemblyAI
        # aai.settings.api_key = os.getenv("AA_ACCESS_KEY")
        # config = aai.TranscriptionConfig(language_code="en", punctuate=False)
        # self._transcriber = aai.Transcriber(config=config)

    @commands.command()
    async def intents(self, ctx):
        await ctx.send(f"```{json.dumps(Assistant.INTENTS, indent=2)}```")

    def _detect_intent(self, audio_frame):
        """
        Detects intent. Inferred intent is pushed to the intent
        queue to be processed.
        """

        # Determine intent from speech
        is_finalized = self.rhino.process(audio_frame)
        if is_finalized:
            inference = self.rhino.get_inference()

            if inference.is_understood:
                self._is_awake = False
                self._resampled_stream = []

                # Add intent to queue and set event for processing
                log.info(inference.intent)
                self._intent_queue.append(inference)
                self._loop.call_soon_threadsafe(self._events["INTENT_DETECTED"].set)

    def say(self, message, quiet_after, after=None):
        """
        Adds a message to the assistant's message queue which will be
        played over the bot's voice client connection using TTS along with
        a text message.

        Audio for the message will only be played if there is no audio
        currently playing. Otherwise, only a text message will be displayed

        Messages will not play over each other and can only played if
        a coroutine to process them exists. In other words, the assistant
        should be enabled for the assistant to broadcast messages.
        """

        utterance = Assistant.Utterance(message, after, quiet_after)
        self._message_queue.append(utterance)

        # Modify the event from another thread using call_soon_threadsafe
        # Reference: https://stackoverflow.com/questions/64651519/how-to-pass-an-event-into-an-async-task-from-another-thread
        self._loop.call_soon_threadsafe(self._events["UTTERANCE_REQUIRED"].set)

    async def _process_message_queue(self):
        """
        A repeating coroutine service that generates speech for
        messages added to message_queue. There should be only one instance
        of this task running.
        """

        while True:
            await self._events["UTTERANCE_FINISHED"].wait()
            await self._events["UTTERANCE_REQUIRED"].wait()

            if len(self._message_queue) > 0:
                # Clear this flag so that coroutines will correctly wait for this event
                self._events["UTTERANCE_FINISHED"].clear()

                log.info("Converting pending message to utterance.")

                utterance: Assistant.Utterance = self._message_queue.popleft()
                music_base = self.client.get_cog("Music")
                audio = await self.get_audio_from_text(utterance.content)
                await music_base.pause(self._ctx)
                log.info("Playback from music cog paused.")
                await self._ctx.send(utterance.content)
                self._voice_client.play(
                    audio,
                    after=lambda _: self._process_message_queue_cb(
                        utterance.quiet_after, utterance.after
                    ),
                )

            self._events["UTTERANCE_REQUIRED"].clear()

    def _process_message_queue_cb(self, quiet_after=False, callback=None):
        if callback:
            callback()

        self._events["UTTERANCE_FINISHED"].set()

        if quiet_after:
            return

        # Resume music if no silence is required after the message
        music_base = self.client.get_cog("Music")
        self._loop.create_task(music_base.resume(self._ctx))

        log.info(f"Success. Utterance transmitted successfully.")

    async def get_audio_from_text(self, message):
        """Converts and returns an Opus-ready audio source from the given message"""

        self._tts_engine.save_to_file(message, "assistant/reply.wav")
        self._tts_engine.runAndWait()
        return await discord.FFmpegOpusAudio.from_probe("assistant/reply.wav")

    async def transcribe(self, prompt):
        """Enables the transcription service and returns the transcription of the shortest phrase captured"""
        self._events["QUERY_DETECTED"].clear()

        music_base = self.client.get_cog("Music")
        await music_base.pause(self._ctx)
        audio = await self.get_audio_from_text(prompt)
        prompt_msg: discord.Message = await self._ctx.send(prompt)
        self._voice_client.play(audio, after=lambda _: self._transcribe_cb())

        log.info("Waiting for transcription to complete")
        await self._events["QUERY_DETECTED"].wait()

        # Stop background whisper transcriber and delete stopper callback
        self._transcription_required = False
        stopper_cb = self._stream_data[self._priority_speaker.id]["stopper"]
        stopper_cb(False)

        await music_base.resume(self._ctx)
        await prompt_msg.edit(content=f'{prompt} "*{self._query.strip()}*"')

        log.info("Returning transcription.")
        return self._query

    def _transcribe_cb(self):
        self._query = None
        self._stream_data[self._priority_speaker.id] = {
            "stopper": None,
            "buffer": array.array("B"),
        }
        self._transcription_required = True

    async def _process_intent(self):
        """A repeating coroutine service to process intents one at a time."""

        while True:
            await self._events["INTENT_DETECTED"].wait()

            if len(self._intent_queue) == 0:
                return

            inference = self._intent_queue.popleft()
            command = self.client.get_command(inference.intent)
            log.info(f"Executing intent: {command}")

            if inference.intent == "play":
                # Additional transcription is required
                prompt_dialog = random.choice(
                    Assistant.DIALOGS["prompts"]["music_selection"]
                )
                query = await self.transcribe(prompt_dialog)
                await command(self._ctx, query=query)
            else:
                # self.say(f"Okay, I will {inference.intent}")
                await command(self._ctx)

            self._events["INTENT_DETECTED"].clear()

    def restore(self, ctx: Context):
        """
        Restores the listening state of the bot.
        Should always be invoked if stop() is called on the voice_client
        """

        self._apply_sink(ctx)

    def _apply_sink(self, ctx: Context):
        """Registers a callback to a BasicSink which is later applied on the bot."""

        def callback(user: discord.User, data: voice_recv.VoiceData):
            # Only process packets from the priority speaker
            if user is None or user.id != self._priority_speaker.id:
                return

            """
            Porcupine expects a frame of 512 samples.

            Each data.pcm array has 3840 bytes. This is because Discord
            is streaming stereo audio at a samplerate of 48kHz at 16 bits.
            The value of 3840 is calculated in the following manner
                (48000 samples * 0.02 seconds * 16 bit depth * 2 channels) / 8
                    = 3840 bytes

            In this case, the bytes of the PCM stream are stored in the format
            below:
                L L R R L L R R L L R R L L R R

            Here, each individual letter represents a single byte. Since each
            sample is measured with 16 bits, two bytes are needed for each
            sample. Additionally, because this PCM stream is stereo (has 2
            channels), the samples of both channels are interleaved such that
            the first sample belongs to the left channel followed by a sample
            belonging to the right and so on.

            Reference:
            https://stackoverflow.com/questions/32128206/what-does-interleaved-stereo-pcm-linear-int16-big-endian-audio-look-like
            """

            log.debug(len(self._resampled_stream))

            if self._transcription_required:
                # Additional speech transcription is required
                sdata = self._stream_data[user.id]
                sdata["buffer"].extend(data.pcm)

                if not sdata["stopper"]:
                    sdata["stopper"] = self.recognizer.listen_in_background(
                        DiscordSRAudioSource(sdata["buffer"]),
                        self._get_bg_listener_callback(user),
                        phrase_time_limit=15,
                    )
            else:
                # Direct all PCM packets to porcupine or rhino if
                # transcription is not required

                # The PCM stream from Discord arrives in bytes in Little Endian format
                values = np.frombuffer(data.pcm, dtype=np.int16)
                value_matrix = np.array((values[::2], values[1::2]))

                # Downsample the audio stream from 48kHz to 16kHz
                resampled_values = resample(value_matrix, 48_000, 16_000).astype(
                    np.int16
                )

                # Extend the buffer with the samples for the current user collected
                # at this instance and choose the left channel only
                self._resampled_stream.extend(resampled_values[0])
                resampled_buffer = self._resampled_stream

                # log.info(self._resampled_stream)

                if len(resampled_buffer) >= 512:
                    # Buffer has >512 bytes
                    audio_frame = resampled_buffer[:512]
                    self._resampled_stream = resampled_buffer[512:]

                    if self.always_awake or self._is_awake:
                        # Determine intent from speech
                        self._detect_intent(audio_frame)
                    else:
                        # Listen for wake word
                        result = self.porcupine.process(audio_frame)
                        # log.info(result)

                        if result >= 0:
                            # Set awake
                            self._is_awake = True
                            self._resampled_stream = []

                            log.info("Detected wake word")
                            dialog = random.choice(
                                Assistant.DIALOGS["prompts"]["general"]
                            )
                            self.say(
                                f"Hi {user.display_name}. {dialog}", quiet_after=True
                            )

        assistant_sink = voice_recv.SilenceGeneratorSink(voice_recv.BasicSink(callback))
        ctx.voice_client.listen(assistant_sink)

    def enable(self, ctx: Context):
        """
        Enables the assistant. When in listening mode, the assistant waits
        for the wake word to trigger command mode. In command mode, the
        assistant will interpret the intent of the speaker who woke the assistant

        :returns: True if the service is enabled or false otherwise
        """

        if not self._services_available:
            log.info(
                "Assistant cannot be enabled because either rhino or porcupine is unavailable."
            )
            return False

        if self.enabled:
            log.info("Assistant is already enabled")
            return False

        self.enabled = True

        # Caching important properties
        self._ctx = ctx
        self._voice_client = ctx.voice_client
        self._priority_speaker = ctx.author

        el = asyncio.get_event_loop()
        self._msg_queue_task = el.create_task(self._process_message_queue())
        self._apply_sink(ctx)

        log.info("Enabled assistant")
        return True

    def disable(self, ctx: Context):
        """
        Disables the assistant and cancels any connections and related tasks
        """

        self.enabled = False
        self._ctx = ctx
        ctx.voice_client.stop_listening()
        self.cleanup()

        log.info("Disabled assistant")

    def cleanup(self):
        # Reset events
        for event in self._events.values():
            event.clear()
        self._events["UTTERANCE_FINISHED"].set()

        # Clean up tasks
        self._msg_queue_task.cancel()

        # Clear queues
        self._message_queue.clear()
        self._intent_queue.clear()

    def _get_bg_listener_callback(self, user: discord.User):
        def callback(recognizer: sr.Recognizer, audio: sr.AudioData):
            if self._query == None:
                # AssemblyAI
                audio_path = "assistant/incoming.wav"
                with open(audio_path, "wb") as fp:
                    fp.write(audio.get_wav_data())

                # self._query = self._transcriber.transcribe(audio_path).text

                # Vosk
                # self.recognizer.vosk_model = vosk.Model("assistant/model")
                # result = json.loads(recognizer.recognize_vosk(audio))
                # self._query = result["text"]

                # Whisper
                self._query = recognizer.recognize_whisper(
                    audio, model="small", language="english"
                )

                self._loop.call_soon_threadsafe(self._events["QUERY_DETECTED"].set)
                log.info(f'{user.display_name} said "{self._query}"')

        return callback


class DiscordSRAudioSource(sr.AudioSource):
    little_endian = True
    SAMPLE_RATE = 48_000
    SAMPLE_WIDTH = 2
    CHANNELS = 2
    CHUNK = 960

    def __init__(self, buffer: array.array):
        self.buffer = buffer
        self._entered: bool = False

    @property
    def stream(self):
        return self

    def __enter__(self):
        if self._entered:
            log.warning("Already entered sr audio source")
        self._entered = True
        return self

    def __exit__(self, *exc) -> None:
        self._entered = False
        if any(exc):
            log.exception("Error closing sr audio source")

    def read(self, size: int) -> bytes:
        # TODO: make this timeout configurable
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
        audiochunk = audioop.tomono(audiochunk, 2, 1, 1)
        return audiochunk

    def close(self) -> None:
        self.buffer.clear()


async def setup(client):
    await client.add_cog(Assistant(client))
