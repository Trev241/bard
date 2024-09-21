import discord
import yt_dlp

import os
import json
import time
import asyncio
import datetime
import traceback

from requests import get
from discord.ext import commands, voice_recv
from collections import deque
from constants import EMBED_COLOR_THEME


class Music(commands.Cog):
    IDLE_TIMEOUT_INTERVAL = 300

    FFMPEG_OPTIONS = {
        "before_options": "-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5",
        "options": "-vn",
    }

    YDL_OPTIONS = {
        "format": "bestaudio",
        "cookiefile": "cookies.txt",
    }

    def __init__(self, client):
        self.client = client
        self.ydl = yt_dlp.YoutubeDL(Music.YDL_OPTIONS)
        self._playback_enabled = asyncio.Event()

        # Convert newline endings in the cookies file
        try:
            with open("cookies.txt", "r") as f:
                cookies_data = f.read().splitlines()
                cookies_data = os.linesep.join(cookies_data)

                print(f"COOKIES: {cookies_data}")
                print(f"Using line separator: {os.linesep}")

            with open("cookies.txt", "w") as f:
                f.write(cookies_data)
        except:
            print("Failed to convert newline endings in cookies")

        self.reset()

    def reset(self):
        """Resets the state of the bot."""

        # Bot state
        self.tts = True
        self.idle = True
        self.skip_track = False
        self.looping_video = False
        self.looping_queue = False

        self.current_track = None
        self._timeout_task = None
        self._ctx = None
        self._track_start_time = None
        self._playback_enabled.set()

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

    @commands.command(aliases=["connect"])
    async def join(self, ctx):
        if ctx.author.voice is None:
            await ctx.send("Please join a voice channel!")
            return False
        else:
            voice_channel = ctx.author.voice.channel
            if ctx.voice_client is None:
                await voice_channel.connect(cls=voice_recv.VoiceRecvClient)
                # await voice_channel.connect()
            else:
                await ctx.voice_client.move_to(voice_channel)

            # Cache context
            self._ctx = ctx
            await self.start_timeout_timer()

            # Prepare assistant
            assistant_base = self.client.get_cog("Assistant")
            if not assistant_base.enabled:
                assistant_base.enable(ctx)

            return True

    @commands.command(aliases=["leave", "quit", "bye"])
    @is_connected()
    async def disconnect(self, ctx):
        ctx.voice_client.stop()
        assistant_base = self.client.get_cog("Assistant")
        assistant_base.disable(ctx)
        self.reset()

        # source = await discord.FFmpegOpusAudio.from_probe('./../sounds/bard.disconnect.ogg')
        # TODO: Resolve sound if bot is launched from main.py
        source = await discord.FFmpegOpusAudio.from_probe(
            "./../bot/sounds/bard.disconnect.ogg"
        )

        el = asyncio.get_running_loop()
        ctx.voice_client.play(
            source, after=lambda error: el.create_task(ctx.voice_client.disconnect())
        )

    @commands.command(aliases=["playing", "nowplaying"])
    @is_connected()
    async def now(self, ctx):
        try:
            # It is possible that the current audio playing is not a music track

            track = self.current_track
            requester = track["requester"]

            embed = discord.Embed.from_dict(
                {
                    "title": track["title"],
                    "description": f'[Click here for video link]({track["webpage_url"]})',
                    "thumbnail": {
                        "url": track["thumbnail"],
                    },
                    "color": 15844367,
                    "fields": [
                        {
                            "name": "Duration",
                            "value": track["duration"],
                            "inline": True,
                        },
                        {
                            "name": "Loop",
                            "value": "Yes" if self.looping_video else "No",
                            "inline": True,
                        },
                        {
                            "name": "Next",
                            "value": (
                                self.queue[1]["title"]
                                if len(self.queue) > 1
                                else (
                                    track["title"]
                                    if self.looping_queue
                                    else "(End of queue)"
                                )
                            ),
                            "inline": True,
                        },
                    ],
                    "footer": {
                        "text": f"Song requested by {requester.display_name}",
                        "icon_url": requester.display_avatar.url,
                    },
                }
            )

            await ctx.send(embed=embed)
        except:
            pass

    @commands.command()
    async def play(self, ctx, *, query):
        # Abort if not in voice channel
        if not await self.join(ctx):
            return

        await ctx.send("Searching...")
        try:
            get(query)
        except:
            info = self.ydl.extract_info(
                f"ytsearch:{query}", download=False, process=False
            )
        else:
            # Avoid downloading by setting process=False to prevent blocking execution
            info = self.ydl.extract_info(query, download=False, process=False)

        # Queue entries
        if info.get("_type", None) == "playlist":
            count = 0

            for entry in info["entries"]:
                await self.queue_entry(entry, ctx)
                count += 1

            await ctx.send(f"Queued {count} video(s).")
        else:
            await self.queue_entry(info, ctx)
            await ctx.send(f'Queued {info["title"]}.')

        self._ctx = ctx

    async def queue_entry(self, entry, ctx):
        self.queue.append(entry)

        # Start playing if bot is idle
        if self.idle:
            self.idle = False
            await self.play_next(ctx)

    def create_track(info, requester):
        """Returns a dict containing a subset of the track's original attributes."""

        url = None
        abr = 0

        for format in info["formats"]:
            if float(format.get("abr", 0) or 0) > abr:
                # Save the URL with the highest audio bit rate
                url = format["url"]

        if type(info["duration"]) is not str:
            info["duration"] = str(datetime.timedelta(seconds=info["duration"]))

        return {
            "type": "processed_music",
            "title": info["title"],
            "url": url,
            "duration": info["duration"],
            "thumbnail": info["thumbnails"][0]["url"],
            "webpage_url": info["webpage_url"],
            "requester": requester,
            # Retaining specific properties
            "start_from": info.get("start_from", 0),
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

        # Pop tracks from the playback queue if
        # 1. The current track is not set to loop
        # 2. Skip count is more than zero
        # 3. Force skip requested
        if (
            not self.looping_video
            or self.skip_track > 0
            or self.current_track.get("force_skip", False)
        ):
            # Skip the number of tracks specified by limit
            # The value 1 is given by default to allow the queue to progress if a track ends naturally
            # i.e. it was neither skipped nor interrupted
            limit = min(max(1, self.skip_track), len(self.queue))

            for _ in range(limit):
                track = self.queue.popleft()

                # Insert the track back at the end of the list if queue is being looped
                if self.looping_queue:
                    self.queue.append(track)
        elif self.looping_video:
            # If no track was popped from the queue, and the current
            # one needs to loop, then reset the start_from property to 0
            self.queue[0]["start_from"] = 0

        # Wait if playback was interrupted
        await self._playback_enabled.wait()

        if len(self.queue) > 0:
            await self.play_next(ctx)
        else:
            self.idle = True
            await self.start_timeout_timer()

        self.skip_track = 0

    async def play_now(self, audio_url):
        """
        Plays an audio source immediately. If there is another audio source
        currently playing, it is temporarily paused.
        """

        interrupting_track = {
            "type": "bot_speech",
            "url": audio_url,
            "start_from": 0,
            "no_looping": True,
        }

        if self.idle:
            self.queue.append(interrupting_track)
            await self.play_next(self._ctx)
        else:
            interrupted_track = self.current_track.copy()
            interrupted_track["start_from"] = int(time.time() - self._track_start_time)

            current_track = self.queue.popleft()
            self.queue.appendleft(interrupted_track)
            self.queue.appendleft(interrupting_track)
            self.queue.appendleft(current_track)

            await self.skip(self._ctx)

    async def start_timeout_timer(self):
        if self._timeout_task:
            self._timeout_task.cancel()
        self._timeout_task = asyncio.get_running_loop().create_task(self.idle_timeout())

    async def idle_timeout(self):
        # Timeout countdown
        await asyncio.sleep(Music.IDLE_TIMEOUT_INTERVAL)

        try:
            voice_client = self._ctx.voice_client
            alone = (
                voice_client
                and len(voice_client.channel.members) == 1
                and voice_client.channel.members[0].id == self.client.user.id
            )
            if alone or self.idle:
                embed = discord.Embed.from_dict(
                    {
                        "title": "Bard is still in development!",
                        "description": "Please be patient if you encounter any bugs. You may also raise them as issues on the [bot's repository](https://github.com/Trev241/bard/issues)",
                        "color": EMBED_COLOR_THEME,
                    }
                )
                await self._ctx.send(embed=embed)

                # It is necessary to pass all required arguments to the function in order for it to execute
                # Calling self.disconnect() alone without any parameters does not actually invoke the function
                # This could be because of some pre-processing done by the decorators attached.
                await self.disconnect(self._ctx)
        except:
            pass

    @is_connected()
    async def play_next(self, ctx):
        try:

            track_type = self.queue[0].get("type", None)
            self.current_track = self.queue[0]
            ffmpeg_opts = {}

            if track_type == "bot_speech":
                self.current_track = self.queue[0]
            else:
                # IE most likely stands for Incomplete Entry (actually stands for Information Extractor)
                # Process IE and probe audio
                if track_type is None:
                    complete_entry = self.ydl.process_ie_result(
                        self.queue[0], download=False
                    )

                    with open("yt-dlp.json", "w") as f:
                        json.dump(
                            self.ydl.sanitize_info(complete_entry), fp=f, indent=2
                        )

                    # If the track was already processed, the same result will be returned
                    self.current_track = Music.create_track(complete_entry, ctx.author)

                # Adjust FFmpeg options to start
                start_from = self.current_track.get("start_from", 0)
                ffmpeg_opts = Music.FFMPEG_OPTIONS.copy()
                ffmpeg_opts["options"] = (
                    ffmpeg_opts.get("options", "") + f" -ss {start_from}"
                )

            source = await discord.FFmpegOpusAudio.from_probe(
                self.current_track["url"], **ffmpeg_opts
            )

            # Fetching Event Loop to create a new task i.e. to play the next song
            # Courtesy of
            # https://stackoverflow.com/questions/69786149/pass-a-async-function-as-a-callback-parameter
            el = asyncio.get_running_loop()
            ctx.voice_client.play(
                source, after=lambda error: el.create_task(self.on_track_complete(ctx))
            )

            # Set start time to current time minus time seeked ahead
            start_from = self.current_track.get("start_from", 0)
            self._track_start_time = time.time() - start_from

            await self.now(ctx)
        except yt_dlp.DownloadError as e:
            traceback.print_exc()
            await ctx.send(f"An error occurred while trying to download the track. {e}")
            await ctx.send("Continuing to next song if available...")

            # End current unplayable track
            await self.on_track_complete(ctx)
        except Exception as e:
            traceback.print_exc()
            await ctx.send(f"An error occurred while trying to play the track. {e}")

            self.reset()

    @play.error
    async def play_error(self, ctx, error):
        await ctx.send(
            f"There was an error while trying to process your request. Error: {error}"
        )

    @commands.group(invoke_without_command=True)
    @is_connected()
    async def loop(self, ctx):
        self.looping_video = not self.looping_video
        await ctx.send(f'{"Looping" if self.looping_video else "Stopped looping"}')

    @loop.command(name="queue", aliases=["all"])
    @is_connected()
    async def loop_queue(self, ctx):
        self.looping_queue = not self.looping_queue
        await ctx.send(
            f'{"Looping queue from current track" if self.looping_queue else "Stopped looping queue"}'
        )

    @commands.command(name="queue", aliases=["q"])
    @is_connected()
    async def show_queue(self, ctx):
        embed = discord.Embed.from_dict(
            {
                "title": f'Bard\'s Queue{" (Looping)" if self.looping_queue else ""}',
                "description": f"{len(self.queue)} track(s) queued.",
                "color": EMBED_COLOR_THEME,
                "fields": [
                    {
                        "name": f'{i + 1}. {track["title"]}',
                        "value": (
                            str(
                                datetime.timedelta(
                                    seconds=(
                                        track["duration"]
                                        if track["duration"] != None
                                        else 0
                                    )
                                )
                            )
                            if type(track["duration"]) is not str
                            else track["duration"]
                        ),
                        "inline": False,
                    }
                    for i, track in enumerate(self.queue)
                ],
            }
        )

        await ctx.send(embed=embed)

    @commands.command()
    @is_connected()
    async def skip(self, ctx, count: int = 1):
        self.skip_track = count

        # Stops the player. Since a callback has already been registered for the current track, there is no need
        # to do anything else. The queue will continue playing as expected.
        ctx.voice_client.stop()

        # Experimental feature in VoiceRecvClient, calling stop() will
        # halt both listening and playback services. There is currently no
        # way to halt one service separately from the other. A temporary workaround
        # is to restart the assistant if it was initially enabled
        assistant_base = self.client.get_cog("Assistant")
        assistant_base.restore(ctx)

    @commands.command()
    @is_connected()
    async def remove(self, ctx, index):
        index = int(index) - 1

        if 0 <= index and index < len(self.queue):
            if index == 0:
                await self.skip(ctx)
            else:
                track = self.queue[index]
                del self.queue[index]
                await ctx.send(f'Removed {track["title"]}')
        else:
            await ctx.send(f"There is no track with that index")

    @commands.command()
    @is_connected()
    async def pause(self, ctx):
        """
        Pauses playback by suspending the music playback cycle
        until a command to resume has been given.
        """

        if len(self.queue) == 0 or not self._playback_enabled.is_set():
            return

        """
        Pausing playback works by creating a copy of the current
        track playing. The only difference being is an additional
        property that is added stating where to begin from. Hence,
        giving the illusion of resuming the track from where it 
        was last paused.

        The current track is then skipped and the playback cycle
        will continue by queuing the copied version of the track 
        next once the interrupt event has been set.

        To counter the quirk of loops not popping the current track,
        an additional property is added to the paused track
        strictly instructing it to forcefully skip even if the track is
        looping
        """

        curr_track_copy = self.current_track.copy()
        curr_track_copy["start_from"] = int(time.time() - self._track_start_time)
        curr_track_orig = self.queue.popleft()
        curr_track_orig["force_skip"] = True
        self.queue.appendleft(curr_track_copy)
        self.queue.appendleft(curr_track_orig)

        self._playback_enabled.clear()
        await self.skip(ctx)

    @commands.command()
    @is_connected()
    async def resume(self, ctx):
        """
        Resumes playback
        """

        # Resume playback by setting flag
        self._playback_enabled.set()


async def setup(client):
    await client.add_cog(Music(client))
