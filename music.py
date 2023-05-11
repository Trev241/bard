import discord
import youtube_dl
import asyncio
import datetime
import traceback

from requests import get
from discord.ext import commands
from collections import deque
from constants import EMBED_COLOR_THEME

class Music(commands.Cog):
    IDLE_TIMEOUT_INTERVAL = 60

    FFMPEG_OPTIONS = {
        'before_options': '-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5',
        'options': '-vn'
    }

    YDL_OPTIONS = {
        'format': 'bestaudio'
    }

    def __init__(self, client):
        self.client = client
        self.ydl = youtube_dl.YoutubeDL(Music.YDL_OPTIONS)

        self.reset()

    def reset(self):
        """Resets the state of the bot."""

        # Bot state
        self.tts = True
        self.idle = True
        self.skip_track = False
        self.removed_first = False
        self.looping_video = False
        self.looping_queue = False
        
        self.current_track = None
        self.timeout_task = None
        self.ctx = None
        
        self.queue = deque()

    def is_connected():
        async def predicate(ctx):
            connected = ctx.voice_client != None
            # The help command utility skips commands for which the predicate check fails. 
            # Hence, it is best not to send any messages here to avoid needless repetitive spam
            # if not connected:
            #     await ctx.send(f'The bot must be in a voice channel for this command to work!')
            return connected
        return commands.check(predicate)

    @commands.command(aliases=['connect'])
    async def join(self, ctx):
        if ctx.author.voice is None:
            await ctx.send('Please join a voice channel!')
            return False
        else:
            voice_channel = ctx.author.voice.channel
            if ctx.voice_client is None:
                await voice_channel.connect()
            else:
                await ctx.voice_client.move_to(voice_channel)
            
            # Cache context
            self.ctx = ctx
            await self.start_timeout_timer()

            return True

    @commands.command(aliases=['leave', 'quit', 'bye'])
    @is_connected()
    async def disconnect(self, ctx):
        ctx.voice_client.stop()
        self.reset()
        
        source = await discord.FFmpegOpusAudio.from_probe('sounds/bard.disconnect.ogg')
        el = asyncio.get_running_loop()
        ctx.voice_client.play(
            source,
            after=lambda error: el.create_task(ctx.voice_client.disconnect())
        )

    @commands.command(aliases=['playing', 'nowplaying'])
    @is_connected()
    async def now(self, ctx):
        track = self.current_track
        requester = track['requester']

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
                'text': f'Song requested by {requester.display_name}',
                'icon_url': requester.display_avatar.url
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

        # Abort if not in voice channel
        if not await self.join(ctx):
            return
        
        await ctx.send('Searching...')
        try:
            get(query)
        except: 
            info = self.ydl.extract_info(f'ytsearch:{query}', download=False, process=False)
        else:
            # Avoid downloading by setting process=False to prevent blocking execution  
            info = self.ydl.extract_info(query, download=False, process=False)
            
        # Queue entries
        if info.get('_type', None) == 'playlist':
            count = 0

            for entry in info['entries']:
                await self.queue_entry(entry, ctx)
                count += 1
            
            await ctx.send(f'Queued {count} video(s).')
        else:
            await self.queue_entry(info, ctx)
            await ctx.send(f'Queued {info["title"]}.')

    async def queue_entry(self, entry, ctx):
        self.queue.append(entry)

        # Start playing if bot is idle
        if self.idle:
            self.idle = False
            await self.play_next(ctx)

    def create_track(info, requester):
        """Returns a dict containing a subset of the track's original attributes."""

        return {
            'title': info['title'],
            'url': info['formats'][0]['url'],
            'duration': str(datetime.timedelta(seconds=info['duration'])),
            'thumbnail': info['thumbnails'][0]['url'],
            'webpage_url': info['webpage_url'],
            'requester': requester
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
            self.idle = True
            await self.start_timeout_timer()
            # self.reset()

        # TODO: Perhaps find a better way to do these?
        # Reset control flags
        self.skip_track = 0
        self.removed_first = False

    async def start_timeout_timer(self):
        if self.timeout_task:
            self.timeout_task.cancel()
        self.timeout_task = asyncio.get_running_loop().create_task(self.idle_timeout())

    async def idle_timeout(self):
        # Timeout countdown
        await asyncio.sleep(Music.IDLE_TIMEOUT_INTERVAL)

        try:
            voice_client = self.ctx.voice_client
            alone = voice_client and len(voice_client.channel.members) == 1 and voice_client.channel.members[0].id == self.client.user.id
            if alone or self.idle:
                embed = discord.Embed.from_dict({
                    'title': 'Bard is still in development!',
                    'description': 'Please be patient if you encounter any bugs. You may also raise them as issues on the [bot\'s repository](https://github.com/Trev241/bard/issues)',
                    'color': EMBED_COLOR_THEME
                })
                await self.ctx.send(embed=embed)
                
                # It is necessary to pass all required arguments to the function in order for it to execute
                # Calling self.disconnect() alone without any parameters does not actually invoke the function
                # This could be because of some pre-processing done by the decorators attached.
                await self.disconnect(self.ctx)
        except:
            pass

    @is_connected()
    async def play_next(self, ctx):
        try:
            # IE most likely stands for Incomplete Entry
            # Process IE and probe audio
            complete_entry = self.ydl.process_ie_result(self.queue[0], download=False)
            self.current_track = Music.create_track(complete_entry, ctx.author)
            source = await discord.FFmpegOpusAudio.from_probe(self.current_track['url'], **Music.FFMPEG_OPTIONS)

            # Fetching Event Loop to create a new task i.e. to play the next song
            # Courtesy of 
            # https://stackoverflow.com/questions/69786149/pass-a-async-function-as-a-callback-parameter
            el = asyncio.get_running_loop()
            ctx.voice_client.play(
                source,
                after=lambda error : el.create_task(self.on_track_complete(ctx))
            )

            await self.now(ctx)
        except:
            traceback.print_exc()
            await ctx.send(f'An error occurred while trying to play the track.')
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
        embed = discord.Embed.from_dict({
            'title': f'Bard\'s Queue{" (Looping)" if self.looping_queue else ""}',
            'description': f'{len(self.queue)} track(s) queued.',
            'color': EMBED_COLOR_THEME,
            'fields': [
                {
                    'name': f'{i + 1}. {track["title"]}',
                    'value': str(datetime.timedelta(seconds=track['duration'])),
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