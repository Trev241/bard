import discord
import youtube_dl
import asyncio
import datetime

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
        self.looping = False
        self.current_track = None
        self.queue = deque()

    @commands.command()
    async def join(self, ctx):
        if ctx.author.voice is None:
            await ctx.send('Please join a voice channel')
        else:
            voice_channel = ctx.author.voice.channel
            if ctx.voice_client is None:
                await voice_channel.connect()
            else:
                await ctx.voice_client.move_to(voice_channel)

    @commands.command()
    async def disconnect(self, ctx):
        # Resetting bot's state
        self.looping = False
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
                'duration': str(datetime.timedelta(seconds=info['duration'])),
                'thumbnail': info['thumbnails'][0]['url'],
            }

            self.queue.append(track)

            # Play track immediately if it is the only element
            if len(self.queue) == 1:
                await self.play_next(ctx)
            else:
                await ctx.send(f'Queued {track["title"]}')

    async def on_track_complete(self, ctx):
        # Pop track if not looping
        if not self.looping:
            self.queue.popleft()
        
        # Continue onto next track if it exists
        if len(self.queue) > 0:
            await self.play_next(ctx)

    async def play_next(self, ctx):
        self.current_track = self.queue[0]

        # Fetching Event Loop to create a new task i.e. to play the next song
        # Courtesy of 
        # https://stackoverflow.com/questions/69786149/pass-a-async-function-as-a-callback-parameter
        el = asyncio.get_event_loop()

        source = await discord.FFmpegOpusAudio.from_probe(self.current_track['url'], **FFMPEG_OPTIONS)

        ctx.voice_client.play(
            source,
            after=lambda error : el.create_task(self.on_track_complete(ctx))
        )

        await ctx.send(f'Now playing: {self.current_track["title"]}')

    @play.error
    async def play_error(self, ctx, error):
        await ctx.send(f'There was an error while trying to process your request. Error: {error}')

    @commands.command()
    async def loop(self, ctx):
        self.looping = not self.looping
        await ctx.send(f'{"Looping" if self.looping else "Stopped looping"}: {self.current_track["title"]}')

    @commands.command(aliases=['queue'])
    async def show_queue(self, ctx):
        tracks = '\n'.join(
            [f'{"[ON LOOP] " if self.looping and i == 0 else ""}{i + 1}. {track["title"]}' for i, track in enumerate(self.queue)]
        )
        await ctx.send(tracks)

    @commands.command()
    async def skip(self, ctx):
        # Stops the player. Since a callback has already been registered for the current track, there is no need
        # to do anything else. The queue will continue playing as expected.
        ctx.voice_client.stop()

        # Turn off looping
        self.looping = False

    @commands.command()
    async def remove(self, ctx, index):
        index = int(index) - 1

        if 0 <= index and index < len(self.queue):
            track = self.queue[index]
            if index == 0:
                # Invoking skip will stop the song and remove it from the queue
                await self.skip(ctx)
            else:
                del self.queue[index]
            await ctx.send(f'Removed {track["title"]}')
        else:
            await ctx.send(f'There is no track with that index')

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