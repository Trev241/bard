import re
import os
import asyncio
import speech_recognition as sr
import pvporcupine
import numpy as np
import resampy
import logging
import pyttsx3
import discord

from discord.ext import commands, voice_recv

logger = logging.getLogger()


class Assistant(commands.Cog):
    def __init__(self, client):
        self.client = client
        self.recognizer = sr.Recognizer()
        self.ctx = None
        self.is_transcribing = False
        self.vc = None

        self.wake_word_buffer = []
        self.porcupine = pvporcupine.create(
            access_key=os.getenv("PV_ACCESS_KEY"),
            keyword_paths=["assistant/Okay-Bard_en_windows_v3_0_0.ppn"],
            # keywords=["picovoice", "bumblebee"],
        )
        self.tts_engine = pyttsx3.init()
        tts_voice_id = self.tts_engine.getProperty("voices")[1].id
        self.tts_engine.setProperty("voice", tts_voice_id)

    @commands.command()
    async def wake(self, ctx):
        self.tts_engine.save_to_file(
            f"Hi, What can I do for you?", "assistant/reply.wav"
        )
        self.tts_engine.runAndWait()
        reply = await discord.FFmpegOpusAudio.from_probe("assistant/reply.wav")
        vc = await ctx.author.voice.channel.connect(cls=voice_recv.VoiceRecvClient)

        def callback(user: discord.User, data: voice_recv.VoiceData):
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
            resampled_values = resampy.resample(value_matrix, 48000, 16000).astype(
                value_matrix.dtype
            )

            # Extend the buffer with the samples collected at this instance
            self.wake_word_buffer.extend(resampled_values[0])

            # Allow porcupine to process the audio if sufficient samples are
            # available
            if len(self.wake_word_buffer) >= 512:
                result = self.porcupine.process(self.wake_word_buffer[:512])
                logger.info(f"Wake word result: {result}")
                self.wake_word_buffer = self.wake_word_buffer[512:]

                if result == 0:
                    vc.play(reply)

        vc.listen(voice_recv.BasicSink(callback))
        # vc.listen(PorcupineSink())

    @commands.command()
    async def listen(self, ctx):
        self.ctx = ctx
        if not self.vc:
            self.vc = await ctx.author.voice.channel.connect(
                cls=voice_recv.VoiceRecvClient
            )
        self.vc.listen(voice_recv.WaveSink(f"sounds/incoming.wav"))

    @commands.command()
    async def transcribe(self, ctx):
        """
        Transcribes the most recent audio instruction recorded
        """
        # Stop listening immediately
        self.vc.stop_listening()

        self.is_transcribing = True
        message = await ctx.send(".")
        el = asyncio.get_event_loop()
        loading_message_task = el.create_task(self.send_loading_message(message))

        audio = sr.AudioFile("sounds/incoming.wav")
        with audio as source:
            audio = self.recognizer.record(source)
            loop = asyncio.get_running_loop()

            # It is absolutely necessary to transcribe the text using
            # asyncio's run_in_executor. If called normally, the call
            # will be blocking and will not allow the loading text to
            # appear
            # Reference: https://stackoverflow.com/questions/77018976/async-loading-images

            result = await loop.run_in_executor(
                None, self.recognizer.recognize_whisper, audio
            )
            # result = self.recognizer.recognize_whisper(audio)

        # Transcription finished
        self.is_transcribing = False
        loading_message_task.cancel()
        result = result.strip().lower()
        await message.edit(content=f'"{result}"')

        # Execute command if available
        args = re.split(r"\s|\,\s", result)
        print(args)
        for command in self.client.commands:
            if command.name == args[0]:
                await ctx.invoke(
                    self.client.get_command(command.name), query=" ".join(args[1:])
                )

        # Delete audio file
        os.remove("sounds/incoming.wav")

    async def send_loading_message(self, message):
        spinner_dot_count = 0

        while self.is_transcribing:
            spinner_dot_count = max(1, (spinner_dot_count + 1) % 6)
            content = "." * spinner_dot_count
            await message.edit(content=content)
            await asyncio.sleep(1)


async def setup(client):
    await client.add_cog(Assistant(client))
