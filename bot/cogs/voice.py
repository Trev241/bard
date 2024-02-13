import re
import os
import asyncio
import speech_recognition as sr

from discord.ext import commands, voice_recv


class Voice(commands.Cog):
    def __init__(self, client):
        self.client = client
        self.recognizer = sr.Recognizer()
        self.ctx = None
        self.is_transcribing = False
        self.vc = None

    @commands.command()
    async def listen(self, ctx): 
        self.ctx = ctx
        if not self.vc:
            self.vc = await ctx.author.voice.channel.connect(cls=voice_recv.VoiceRecvClient)
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
            
            result = await loop.run_in_executor(None, self.recognizer.recognize_whisper, audio)
            # result = self.recognizer.recognize_whisper(audio)
       
        # Transcription finished
        self.is_transcribing = False
        loading_message_task.cancel()
        result = result.strip().lower()
        await message.edit(content=f"\"{result}\"")

        # Execute command if available
        args = re.split(r"\s|\,\s", result)
        print(args)
        for command in self.client.commands:
            if command.name == args[0]:
                await ctx.invoke(self.client.get_command(command.name), query=" ".join(args[1:]))

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
    await client.add_cog(Voice(client))