import discord
import youtube_dl
import asyncio

from discord.ext import commands
from collections import deque

FFMPEG_OPTIONS = {
    'before_options': '-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5',
    'options': '-vn'
}

YDL_OPTIONS = {
    'format': 'bestaudio'
}

IDLE_TIMEOUT_INTERVAL = 3

class Music(commands.Cog):
    def __init__(self, client):
        self.client = client

        self.idle = True
        self.looping = False
        self.current_track = None
        self.queue = deque()

    @commands.command()
    async def join(self, ctx):
        if ctx.author.voice is None:
            await ctx.send("Please join a voice channel")
        else:
            voice_channel = ctx.author.voice.channel
            if ctx.voice_client is None:
                await voice_channel.connect()
            else:
                await ctx.voice_client.move_to(voice_channel)

    @commands.command()
    async def disconnect(self, ctx):
        # Resetting bot's state
        self.idle = True
        self.loop = False
        self.current_track = None
        self.queue = deque()

        await ctx.voice_client.disconnect()

    @commands.command()
    async def play(self, ctx, url):
        # Join voice channel
        await self.join(ctx)

        with youtube_dl.YoutubeDL(YDL_OPTIONS) as ydl:
            info = ydl.extract_info(url, download=False)
            track = {
                'title': info['title'],
                'url': info['formats'][0]['url'],
                'duration': f'{int(info["duration"] / 60)}:{info["duration"] % 60}',
                'thumbnail': info['thumbnails'][0]['url'],
                'source': await discord.FFmpegOpusAudio.from_probe(info['formats'][0]['url'], **FFMPEG_OPTIONS),
            }
            self.queue.append(track)

            if self.idle:
                await self.play_next(ctx)
            else:
                await ctx.send(f'Queued {track["title"]}')

    async def play_next(self, ctx):
        if len(self.queue) > 0:
            self.idle = False
            
            # if not self.looping:
            self.current_track = self.queue.popleft()

            # Fetching Event Loop to create a new task i.e. to play the next song
            # Courtesy of 
            # https://stackoverflow.com/questions/69786149/pass-a-async-function-as-a-callback-parameter
            el = asyncio.get_event_loop()

            ctx.voice_client.play(
                self.current_track['source'], 
                after=lambda error : el.create_task(self.play_next(ctx))
            )

            await ctx.send(f'Now playing: {self.current_track["title"]}')
        else:
            self.idle = True
            await ctx.send('Reached the end of the queue')

    @play.error
    async def play_error(self, ctx, error):
        await ctx.send(f'There was an error while trying to process your request. Error: {error}')

    @commands.command()
    async def loop(self, ctx):
        self.looping = not self.looping
        await ctx.send(f'Looping {self.current_track["title"]}')
        
    @commands.command()
    async def pause(self, ctx):
        ctx.voice_client.pause()
        await ctx.send('Paused')

    @commands.command()
    async def resume(self, ctx):
        ctx.voice_client.resume()
        await ctx.send('Resumed')

async def setup(client):
    await client.add_cog(Music(client))