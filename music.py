import discord
import youtube_dl
import asyncio
import datetime

from requests import get
from discord.ext import commands
from collections import deque
from constants import IDLE_TIMEOUT_INTERVAL, EMBED_COLOR_THEME

FFMPEG_OPTIONS = {
    'before_options': '-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5',
    'options': '-vn'
}

YDL_OPTIONS = {
    'format': 'bestaudio'
}

class Music(commands.Cog):
    def __init__(self, client):
        self.client = client
        self.reset()

    def reset(self):
        """Resets the state of the bot."""

        self.idle = True
        self.skip_track = False
        self.removed_first = False
        self.looping_video = False
        self.looping_queue = False
        self.current_track = None
        self.tts = True

        self.queue = deque()

    def is_connected():
        async def predicate(ctx):
            connected = ctx.voice_client != None
            if not connected:
                await ctx.send(f'The bot must be in a voice channel for this command to work!')
            return connected
        return commands.check(predicate)

    async def idle_timeout(self, ctx):
        while True:
            await asyncio.sleep(IDLE_TIMEOUT_INTERVAL)
            
            alone = ctx.voice_client and len(ctx.voice_client.channel.members) == 1

            if alone or self.idle:
                try:
                    embed = discord.Embed.from_dict({
                      'title': 'Bard is still in development!',
                      'description': 'Please be patient if you encounter any bugs. You may also raise them as issues on the [bot\'s repository](https://github.com/Trev241/bard/issues)',
                      'color': EMBED_COLOR_THEME
                    })
                    await ctx.send(embed=embed)
                    await self.disconnect(ctx)
                except:
                    pass
                break

    @commands.command(aliases=['connect'])
    async def join(self, ctx):
        if ctx.author.voice is None:
            await ctx.send('Please join a voice channel')
        else:
            voice_channel = ctx.author.voice.channel
            if ctx.voice_client is None:
                await voice_channel.connect()
            else:
                await ctx.voice_client.move_to(voice_channel)

            # Create task that checks if the bot is idle
            el = asyncio.get_event_loop()
            el.create_task(self.idle_timeout(ctx))

    @commands.command(aliases=['leave', 'quit', 'bye'])
    @is_connected()
    async def disconnect(self, ctx):
        await ctx.voice_client.disconnect()
        self.reset()

    @commands.command(aliases=['playing', 'nowplaying'])
    @is_connected()
    async def now(self, ctx):
        track = self.current_track
        cmd_author = track['cmd_author']

        embed = discord.Embed.from_dict({
            'title': track['title'],
            'description': f'[Click here for video link]({track["webpage_url"]})',
            'thumbnail': {
                'url': track['thumbnail'],
            },
            'color': 15844367,
            'fields': [
                {
                    'name': 'Duration',
                    'value': track['duration'],
                    'inline': True
                },
                {
                    'name': 'Loop',
                    'value': 'Yes' if self.looping_video else 'No',
                    'inline': True
                },
                {
                    'name': 'Next',
                    'value': self.queue[1]['title'] if len(self.queue) > 1 else track['title'] if self.looping_queue else '(End of queue)',
                    'inline': True
                },
            ],
            'footer': {
                'text': f'Song requested by {cmd_author.display_name}',
                'icon_url': cmd_author.display_avatar.url
            }
        })

        if self.tts:
            await ctx.send(f'Now playing {track["title"]}', tts=True, delete_after=30)

        await ctx.send(embed=embed)

    @commands.command(name='tts')
    async def tts_(self, ctx, flag: bool):
        self.tts = flag
        await ctx.send(f'TTS {"enabled" if self.tts else "disabled"}')

    @commands.command()
    async def play(self, ctx, *, query):
        # Join voice channel
        await self.join(ctx)

        with youtube_dl.YoutubeDL(YDL_OPTIONS) as ydl:
            await ctx.send('Searching... (this may take some time if you have queued a playlist)')

            try:
                get(query)
            except: 
                info = ydl.extract_info(f'ytsearch:{query}', download=False)
            else:
                info = ydl.extract_info(query, download=False)

            # Debugging
            # with open('youtube_dl_info.txt', 'w') as f:
            #     json.dump(info, f, ensure_ascii=True, indent=4)

            # Determine if playlist or a single video. All other formats are ignored for now
            if info.get('_type', None) == 'playlist':

                for entry in info['entries']:
                    entry['cmd_author'] = ctx.author
                    self.queue.append(Music.create_track(entry))
            
                await ctx.send(f'Queued {len(info["entries"])} entr(y/ies)')

            elif 'formats' in info:

                info['cmd_author'] = ctx.author
                track = Music.create_track(info)
                self.queue.append(track)
                await ctx.send(f'Queued {track["title"]}')

            else:

                await ctx.send('Unsupported format')
                return


            # Commence playback if bot is idle
            if self.idle:
                self.idle = False
                await self.play_next(ctx)

    def create_track(info):
        """Returns a dict containing a subset of the track's original attributes."""

        return {
            'title': info['title'],
            'url': info['formats'][0]['url'],
            'duration': str(datetime.timedelta(seconds=info['duration'])),
            'thumbnail': info['thumbnails'][0]['url'],
            'webpage_url': info['webpage_url'],
            'cmd_author': info['cmd_author']
        }

    async def on_track_complete(self, ctx):
        """
        Callback for when a track has completed playing either by exhausting its source or through interruption.
        The decision on how to manage the queue is based on the current state of the bot.

        If the bot is looping a single track, then the track at the front of the queue is not removed.
        If the bot is skipping a track, then the track at the front of the queue is removed
        If the bot is looping the queue, then the track at the front of the queue is removed and inserted at the rear.
        
        If both flags are true (i.e. loop single as well as queue), then the task of looping the single track takes
        higher priority over looping the queue as one would expect intuitively. In other words, the next track
        will not be played unless looping for the current track has been turned off. This is because the track  
        at the front of the queue is not popped.

        At the end of the callback, if there are still items in the queue, then play_next() is called to play
        the next track at the head of the queue.
        """

        # Pop the first track if
        # 1. Not looping single
        # 2. Skip count is more than zero
        # BUT DO NOT REMOVE if it already has been removed
        if (not self.looping_video or self.skip_track > 0) and not self.removed_first:

            # Skip the number of tracks specified by limit
            # The value 1 is given by default to allow the queue to progress if a track ends naturally
            # i.e. it was neither skipped nor interrupted
            limit = min(max(1, self.skip_track), len(self.queue))

            for _ in range(limit):
                track = self.queue.popleft()

                # Insert the track back at the end of the list if queue is being looped
                if self.looping_queue:
                    self.queue.append(track)
        
        # Continue onto next track if it exists
        if len(self.queue) > 0:
            await self.play_next(ctx)
        else:
            self.reset()

        # TODO: Perhaps find a better way to do these?
        # Reset control flags
        self.skip_track = 0
        self.removed_first = False

    @is_connected()
    async def play_next(self, ctx):
        try:
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

            # await ctx.send(f'Now playing: {self.current_track["title"]}')
            await self.now(ctx)
        except:
            await ctx.send(f'Could not play track. Bot was unexpectedly disconnected before playback could commence.')
            self.reset()

    @play.error
    async def play_error(self, ctx, error):
        await ctx.send(f'There was an error while trying to process your request. Error: {error}')

    @commands.group(invoke_without_command=True)
    @is_connected()
    async def loop(self, ctx):
        self.looping_video = not self.looping_video
        await ctx.send(f'{"Looping" if self.looping_video else "Stopped looping"}: {self.current_track["title"]}')

    @loop.command(name='queue', aliases=['all'])
    @is_connected()
    async def loop_queue(self, ctx):
        self.looping_queue = not self.looping_queue
        await ctx.send(f'{"Looping queue from current track" if self.looping_queue else "Stopped looping queue"}')

    @commands.command(name='queue', aliases=['q'])
    @is_connected()
    async def show_queue(self, ctx):
        # tracks = ('[ON LOOP] ' if self.looping_video else '') + '\n'.join(
        #     [f'{i + 1}.\t{track["title"]}' for i, track in enumerate(self.queue)]
        # ) + ('\n[LOOP BACK TO HEAD]' if self.looping_queue else '')

        # await ctx.send(tracks)

        embed = discord.Embed.from_dict({
            'title': f'Bard\'s Queue{" (Looping)" if self.looping_queue else ""}',
            'description': f'{len(self.queue)} track(s) queued.',
            'color': EMBED_COLOR_THEME,
            'fields': [
                {
                    'name': f'{i + 1}. {track["title"]}',
                    'value': track['duration'],
                    'inline': False
                } for i, track in enumerate(self.queue)
            ]
        })

        await ctx.send(embed=embed)

    @commands.command()
    @is_connected()
    async def skip(self, ctx, count: int = 1):
        self.skip_track = count 

        # Stops the player. Since a callback has already been registered for the current track, there is no need
        # to do anything else. The queue will continue playing as expected.
        ctx.voice_client.stop()

    @commands.command()
    @is_connected()
    async def remove(self, ctx, index):
        index = int(index) - 1

        if 0 <= index and index < len(self.queue):

            track = self.queue[index]
            del self.queue[index]
            if index == 0:
                self.removed_first = True
                await self.skip(ctx)
            await ctx.send(f'Removed {track["title"]}')

        else:
            await ctx.send(f'There is no track with that index')

    @commands.command()
    @is_connected()
    async def pause(self, ctx):
        ctx.voice_client.pause()
        await ctx.send('Paused')

    @commands.command()
    @is_connected()
    async def resume(self, ctx):
        ctx.voice_client.resume()
        await ctx.send('Resumed')

async def setup(client):
    await client.add_cog(Music(client))