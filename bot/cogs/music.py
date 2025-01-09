import discord
import yt_dlp

import os
import json
import time
import random
import asyncio
import datetime
import traceback
import logging

from requests import get
from discord.ext import commands, voice_recv
from collections import deque
from bot import EMBED_COLOR_THEME, socketio
from bot.models import MusicRequest, Source

log = logging.getLogger(__name__)


class Music(commands.Cog):
    IDLE_TIMEOUT_INTERVAL = 300

    FFMPEG_OPTIONS = {
        "before_options": "-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5",
        "options": "-vn",
    }

    YDL_LOGGER = logging.getLogger("yt-dlp")
    YDL_LOGGER.setLevel(logging.DEBUG)
    YDL_LOG_HANDLER = logging.StreamHandler()
    YDL_LOGGER.addHandler(YDL_LOG_HANDLER)

    YDL_OPTIONS = {
        "format": "bestaudio",
        "cookiefile": "bot/cookies.txt",
        "verbose": False,
        "quiet": False,
        "logger": YDL_LOGGER,
    }

    AUTO_PLAYLIST = (
        "https://www.youtube.com/playlist?list=PL7Akty-aEXMq8x9ToQy7v4TxLsi42MHSd"
    )

    def __init__(self, client):
        # Convert newline endings in the cookies file
        try:
            with open("bot/cookies.txt", "r") as f:
                cookies_data = f.read()

            cookies_data = (
                cookies_data.replace("\r\n", "\n")
                .replace("\r", "\n")
                .replace("\n", os.linesep)
            )

            with open("bot/cookies.txt", "w", newline="") as f:
                f.write(cookies_data)
        except Exception as e:
            log.error(f"Failed to convert newline endings in cookies: {e}")

        self.client = client
        self._playback_enabled = asyncio.Event()

        self.load_handlers()
        self.reset()

    def reset(self):
        """Resets the state of the bot."""

        # Bot state
        self.tts = True
        self.idle = True
        self.skip_track = False
        self.looping_video = False
        self.looping_queue = False
        self.auto_play = True
        self.auto_play_tracks = []
        self.voice_channel = None
        self.public_url = None

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

    def load_handlers(self):
        el = asyncio.get_event_loop()

        @socketio.on("playback_track_request")
        def handle_track_request(json=None):
            task = el.create_task(
                self.play(
                    MusicRequest(
                        query=json["query"],
                        author=self.client.user,
                        ctx=self._ctx,
                        source=Source.WEB,
                    )
                )
            )
            task.add_done_callback(lambda _: on_handle_complete())

        @socketio.on("playback_instruct_play")
        def handle_play(json=None):
            # Create an async task to play/pause the current track
            is_playing = self._ctx.voice_client.is_playing()
            if is_playing:
                self.pause(self._ctx)
            else:
                self.resume(self._ctx)
            on_handle_complete()

        @socketio.on("playback_instruct_skip")
        def handle_skip(json=None):
            # Create an async task to skip the current track
            self.skip(self._ctx)
            on_handle_complete()

        @socketio.on("playback_instruct_loop")
        def handle_loop(json=None):
            # Create an async task to loop the current track
            self.loop()
            on_handle_complete({"is_looping": self.looping_video})

        def on_handle_complete(data=None):
            socketio.emit("playback_instruct_done", data)

    @commands.command(aliases=["connect"])
    async def join(self, ctx):
        self._ctx = ctx
        if ctx.author.voice is None:
            await ctx.send("Please join a voice channel!")
            return False

        await self.join_vc(ctx)

        # try:
        #     response = get("http://localhost:4040/api/tunnels")
        #     self.public_url = response.json()["tunnels"][0]["public_url"]
        #     await ctx.send(f"Visit {self.public_url}/dashboard to manage me!")
        # except Exception:
        #     log.error(
        #         "There was an error trying to fetch the public URL of ngrok's agent."
        #     )

        return True

    @staticmethod
    def gen_auto_playlist():
        """
        Returns a shuffled playlist of tracks to play automatically when the bot is idle
        """

        ydl = yt_dlp.YoutubeDL(Music.YDL_OPTIONS)
        info = ydl.extract_info(Music.AUTO_PLAYLIST, download=False, process=False)
        auto_play_tracks = deque()
        for entry in info["entries"]:
            auto_play_tracks.append(entry)
        random.shuffle(auto_play_tracks)

        return auto_play_tracks

    async def join_vc(self, ctx, voice_channel=None, author=None):
        """
        Instructs the bot to join the voice channel. If voice_channel and author
        are not provided, they will be taken from the context instead.
        """

        # Load auto-play tracks when the bot connects
        self.auto_play_tracks = Music.gen_auto_playlist()

        voice_channel = voice_channel or ctx.author.voice.channel
        ctx.author = author or ctx.author

        if ctx.voice_client is None:
            await voice_channel.connect(cls=voice_recv.VoiceRecvClient)
            # await voice_channel.connect()

            # Prepare assistant
            assistant_base = self.client.get_cog("Assistant")
            if not assistant_base.enabled:
                # Enable the assistant
                assistant_connected = assistant_base.enable(ctx)

                # Let the user know at least once if voice commands are enabled or not
                if not assistant_connected:
                    await ctx.send(
                        f"Hey! My hearing is a little bad today so I won't be able to take voice commands from you. As always, you can always type in your instructions instead."
                    )
                else:
                    await ctx.send(
                        f"Hey! You can also give me commands by just saying it out loud! Type `?intents` if you need help."
                    )
        else:
            await ctx.voice_client.move_to(voice_channel)

        # Cache context
        self._ctx = ctx
        self.voice_channel = voice_channel
        await self.start_timeout_timer()

    @commands.command(aliases=["leave", "quit", "bye"])
    @is_connected()
    async def disconnect(self, ctx):
        # Temporarily disable some flags to allow the bot to exit
        self.looping_video = self.auto_play = False

        ctx.voice_client.stop()
        assistant_base = self.client.get_cog("Assistant")
        assistant_base.disable(ctx)

        source = await discord.FFmpegOpusAudio.from_probe(
            "bot/sounds/bard.disconnect.ogg"
        )

        def after_callback(error):
            coro = ctx.voice_client.disconnect()
            fut = asyncio.run_coroutine_threadsafe(coro, self.client.loop)
            try:
                fut.result()
            except:
                pass

        ctx.voice_client.play(source, after=after_callback)

        self.reset()
        socketio.emit("playback_stop")

    @commands.command(aliases=["playing", "nowplaying"])
    @is_connected()
    async def now(self, ctx):
        try:
            # It is possible that the current audio playing is not a music track

            track = self.current_track
            requester = track["requester"]
            footer_text = (
                f"Played automatically by me. This song will be skipped as soon as you play something else!"
                if track["requester"] == self.client.user
                else f"Song requested by {requester.display_name}"
            )

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
                        "text": footer_text,
                        "icon_url": requester.display_avatar.url,
                    },
                }
            )

            await ctx.send(embed=embed)
        except:
            pass

    async def play(self, request: MusicRequest):
        ctx = request.ctx
        ydl = yt_dlp.YoutubeDL(Music.YDL_OPTIONS)

        if self._ctx is None or self._ctx.voice_client is None:
            log.error("Failed to play track, bot must be connected to a voice channel.")
            return

        # Qualify the message object of the request
        if request.source == Source.WEB:
            msg = await ctx.send(f'Received on the web player: "{request.query}".')
            request.msg = msg
        else:
            request.msg = ctx.message

        try:
            get(request.query)
        except:
            info = ydl.extract_info(
                f"ytsearch:{request.query}", download=False, process=False
            )
        else:
            # Avoid downloading by setting process=False to prevent blocking execution
            info = ydl.extract_info(request.query, download=False, process=False)

        # If a single track is returned, convert it into a list for consistency in format
        entries = info["entries"] if info.get("_type", None) == "playlist" else [info]
        count = 0
        for entry in entries:
            entry["requester"] = request.author
            await self.queue_entry(entry, request)
            count += 1

        if count == 1:
            await ctx.send(f"Queued track")
        else:
            await ctx.send(f"Queued {count} tracks")

    @commands.command(name="play")
    async def _play(self, ctx, *, query):
        # Abort if not in voice channel or query is missing
        if not await self.join(ctx) or query is None:
            return

        await ctx.send("Searching...")
        await self.play(MusicRequest(query, ctx.author, ctx, Source.CMD))

    async def queue_entry(self, entry, request: MusicRequest):
        self.queue.append(entry)
        ctx = request.ctx
        # Submit analytics data
        self.client.get_cog("Analytics").submit_track(
            request.msg.id,
            request.msg.channel.id,
            request.msg.guild.id,
            entry["title"],
            request.author.id,
            request.msg.created_at,
        )

        if self.idle:
            # Play immediately if the bot is idle or if playing elevator music
            self.idle = False
            await self.play_next(ctx)
        elif self.current_track.get("elevator_music", False):
            # Skip the current track if it's from the auto-playlist
            self.skip(ctx)

        socketio.emit(
            "playlist_update",
            {"queue": Music.simplify_queue(list(self.queue))},
        )

    @staticmethod
    def simplify_queue(queue):
        return [
            {
                "title": track["title"],
                "thumbnail": track["thumbnails"][-1]["url"],
                "duration": (
                    track["duration"]
                    if type(track["duration"]) is str and ":" in track["duration"]
                    else str(datetime.timedelta(seconds=int(track["duration"])))
                ),
            }
            for track in queue
        ]

    def create_track(self, info):
        """
        Processes the incomplete entry and returns a dict containing a subset of
        the track's original attributes and some other properties set by the cog.
        """

        ydl = yt_dlp.YoutubeDL(Music.YDL_OPTIONS)
        processed_entry = ydl.process_ie_result(info, download=False)
        with open("bot/yt-dlp.json", "w") as f:
            json.dump(ydl.sanitize_info(processed_entry), fp=f, indent=2)

        url = None
        abr = 0

        for format in processed_entry["formats"]:
            if float(format.get("abr", 0) or 0) > abr:
                # Save the URL with the highest audio bit rate
                url = format["url"]

        track = {}
        for k, v in processed_entry.items():
            track[k] = v

        track["title"] = processed_entry["title"]
        track["url"] = url
        track["duration"] = str(datetime.timedelta(seconds=int(info["duration"])))
        track["thumbnail"] = processed_entry["thumbnails"][0]["url"]
        track["webpage_url"] = processed_entry["webpage_url"]
        track["requester"] = info.get("requester", self.client.user)
        # Retaining specific properties
        track["start_from"] = info.get("start_from", 0)
        track["elevator_music"] = info.get("elevator_music", False)

        return track

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

        if self.auto_play and len(self.queue) == 0:
            if len(self.auto_play_tracks) == 0:
                # If all tracks in the playlist are exhausted
                self.auto_play_tracks = Music.gen_auto_playlist()

            track = self.auto_play_tracks.popleft()
            track["elevator_music"] = True
            self.queue.append(track)

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

            self.skip(self._ctx)

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
                    # If the track was already processed, the same result will be returned
                    self.current_track = self.create_track(self.queue[0])

                # Adjust FFmpeg options to start
                start_from = self.current_track.get("start_from", 0)
                ffmpeg_opts = Music.FFMPEG_OPTIONS.copy()
                ffmpeg_opts["options"] = (
                    ffmpeg_opts.get("options", "") + f" -ss {start_from}"
                )

            source = await discord.FFmpegOpusAudio.from_probe(
                self.current_track["url"], **ffmpeg_opts
            )

            # Reference:
            # https://discordpy.readthedocs.io/en/stable/faq.html#how-do-i-pass-a-coroutine-to-the-player-s-after-function
            def after_callback(error):
                coro = self.on_track_complete(ctx)
                fut = asyncio.run_coroutine_threadsafe(coro, self.client.loop)
                try:
                    fut.result()
                except:
                    pass

            ctx.voice_client.play(source, after=after_callback)

            # Set start time to current time minus time seeked ahead
            start_from = self.current_track.get("start_from", 0)
            self._track_start_time = time.time() - start_from

            socketio.emit(
                "playing_track",
                {
                    "title": self.current_track["title"],
                    "thumbnail": self.current_track["thumbnails"][-1]["url"],
                    "requester": self.current_track["requester"].display_name,
                    "webpage_url": self.current_track["webpage_url"],
                    "queue": Music.simplify_queue(list(self.queue)),
                },
            )
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

    @_play.error
    async def play_error(self, ctx, error):
        await ctx.send(
            f"There was an error while trying to process your request. Error: {error}"
        )

    def loop(self):
        self.looping_video = not self.looping_video
        socketio.emit("playback_state", {"looping": self.looping_video})

    @commands.group(name="loop", invoke_without_command=True)
    @is_connected()
    async def _loop(self, ctx):
        self.loop()
        await ctx.send(f'{"Looping" if self.looping_video else "Stopped looping"}')

    @_loop.command(name="queue", aliases=["all"])
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

    def skip(self, ctx, count=1):
        self.skip_track = count
        assistant_base = self.client.get_cog("Assistant")
        restart_assistant = assistant_base.enabled

        # Stops the player. Since a callback has already been registered for the current track, there is no need
        # to do anything else. The queue will continue playing as expected.
        ctx.voice_client.stop()

        # Experimental feature in VoiceRecvClient, calling stop() will
        # halt both listening and playback services. There is currently no
        # way to halt one service separately from the other. A temporary workaround
        # is to restart the assistant if it was initially enabled
        if restart_assistant:
            # Only restart the assistant if it was initially enabled
            assistant_base.restore(ctx)

    @commands.command(name="skip")
    @is_connected()
    async def _skip(self, ctx, count: int = 1):
        self.skip(ctx, count)

    @commands.command()
    @is_connected()
    async def remove(self, ctx, index):
        index = int(index) - 1

        if 0 <= index and index < len(self.queue):
            if index == 0:
                self.skip(ctx)
            else:
                track = self.queue[index]
                del self.queue[index]
                await ctx.send(f'Removed {track["title"]}')
        else:
            await ctx.send(f"There is no track with that index")

    def pause(self, ctx):
        """
        Pause playback normally. You cannot play anything else until
        the ongoing track has completed
        """

        ctx.voice_client.pause()
        socketio.emit("playback_state", {"playing": ctx.voice_client.is_playing()})

    @commands.command(name="pause")
    @is_connected()
    async def _pause(self, ctx):
        self.pause(ctx)

    async def suspend(self, ctx):
        """
        Pauses playback by suspending the music playback cycle
        until a command to resume has been given.

        This is different from a regular pause. Use this if you
        want to play a different track while also allowing you
        to resume from the old track once you are finished.
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
        self.skip(ctx)

    def resume(self, ctx):
        ctx.voice_client.resume()
        socketio.emit("playback_state", {"playing": ctx.voice_client.is_playing()})

    @commands.command(name="resume")
    @is_connected()
    async def _resume(self, ctx):
        """
        Resumes playback
        """

        self.resume(ctx)

    def remove_suspension(self):
        """
        Resume playback of a suspended track
        Not to be confused with resume
        """
        self._playback_enabled.set()

    def is_playback_paused(self):
        return not self._playback_enabled.is_set()


async def setup(client):
    await client.add_cog(Music(client))
