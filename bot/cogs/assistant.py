import os
import speech_recognition as sr
import pvporcupine
import numpy as np
import resampy
import logging
import pyttsx3
import discord
import audioop
import array
import time
import pvrhino
import asyncio

from discord.ext import commands, voice_recv
from collections import defaultdict

log = logging.getLogger()


class Assistant(commands.Cog):
    def __init__(self, client):
        # Bot state
        self.client = client
        self.recognizer = sr.Recognizer()
        self.ctx = None
        self.is_transcribing = False
        self.vc = None
        self.is_awake = False
        self._resampled_stream = defaultdict(lambda: list())
        self._stream_data = defaultdict(
            lambda: {"stopper": None, "buffer": array.array("B")}
        )

        # Porcupine wake-word
        self.speaker = None
        self.porcupine = pvporcupine.create(
            access_key=os.getenv("PV_ACCESS_KEY"),
            keyword_paths=["assistant/Okay-Bard_en_windows_v3_0_0.ppn"],
            # keywords=["picovoice", "bumblebee"],
        )

        # TTS
        self.tts_engine = pyttsx3.init()
        tts_voice_id = self.tts_engine.getProperty("voices")[1].id
        self.tts_engine.setProperty("voice", tts_voice_id)

        # Rhino speech-to-intent
        self.last_frame_time = None
        self.rhino = pvrhino.create(
            access_key=os.getenv("PV_ACCESS_KEY"),
            context_path="assistant/Bard-Assistant_en_windows_v3_0_0.rhn",
            require_endpoint=False,  # Rhino will not require an chunk of silence at the end
        )

    async def detect_silence(self):
        while self.is_awake:
            await asyncio.sleep(0.1)
            curr_time = time.time_ns() // 1_000_000

            # Check if 500ms of silence has elapsed
            if curr_time - self.last_frame_time > 500:
                # Rhino will only infer intent after a chunk of silence
                silence_frame = [0 for _ in range(512)]
                self.detect_intent(silence_frame)

                return

    def detect_intent(self, audio_frame):
        # Determine intent from speech
        is_finalized = self.rhino.process(audio_frame)
        if is_finalized:
            inference = self.rhino.get_inference()

            if inference.is_understood:
                self.is_awake = False
                log.info(inference.intent)

    @commands.command()
    async def wake(self, ctx):
        self.tts_engine.save_to_file(
            f"Hi, What can I do for you?", "assistant/reply.wav"
        )
        self.tts_engine.runAndWait()
        reply = await discord.FFmpegOpusAudio.from_probe("assistant/reply.wav")
        vc = await ctx.author.voice.channel.connect(cls=voice_recv.VoiceRecvClient)

        def callback(user: discord.User, data: voice_recv.VoiceData):
            # log.info(f"Got packet from {user.display_name}")

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

            # The PCM stream from Discord arrives in bytes in Little Endian format
            values = np.frombuffer(data.pcm, dtype=np.int16)
            value_matrix = np.array((values[::2], values[1::2]))

            # Downsample the audio stream from 48kHz to 16kHz
            resampled_values = resampy.resample(value_matrix, 48_000, 16_000).astype(
                value_matrix.dtype
            )

            # Extend the buffer with the samples collected at this instance
            # and choose left channel only
            self._resampled_stream[user.id].extend(resampled_values[0])
            resampled_buffer = self._resampled_stream[user.id]

            # Mark the timestamp of this audio frame as the most recent one received
            self.last_frame_time = time.time_ns() // 1_000_000

            if len(resampled_buffer) >= 512:
                # Buffer has >512 bytes
                audio_frame = resampled_buffer[:512]
                self._resampled_stream[user.id] = resampled_buffer[512:]

                if self.is_awake:
                    # Determine intent from speech
                    self.detect_intent(audio_frame)
                else:
                    # Listen for wake word
                    result = self.porcupine.process(audio_frame)

                    if result == 0:
                        # Set awake
                        self.is_awake = True
                        self.speaker = user
                        log.info("Detected wake word")

                        # el = asyncio.get_event_loop()
                        # el.create_task(self.detect_silence())

                        vc.play(reply)

            # elif self.speaker != None and self.speaker.id == user.id:
            #     sdata = self._stream_data[user.id]
            #     sdata["buffer"].extend(data.pcm)

            #     if not sdata["stopper"]:
            #         sdata["stopper"] = self.recognizer.listen_in_background(
            #             DiscordSRAudioSource(sdata["buffer"]),
            #             self.get_bg_listener_callback(user),
            #             phrase_time_limit=10,
            #         )

        assistant_sink = voice_recv.SilenceGeneratorSink(voice_recv.BasicSink(callback))
        vc.listen(assistant_sink)

    def get_bg_listener_callback(self, user: discord.User):
        def callback(recognizer: sr.Recognizer, audio):
            output = recognizer.recognize_whisper(
                audio, model="tiny", language="english"
            )
            print(f'{user.display_name} said "{output}"')

        return callback


class DiscordSRAudioSource(sr.AudioSource):
    little_endian = True
    SAMPLE_RATE = 48_000
    SAMPLE_WIDTH = 2
    CHANNELS = 2
    CHUNK = 960

    def __init__(self, buffer: array.array[int]):
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
