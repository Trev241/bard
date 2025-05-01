import os
import asyncio
import logging
import itertools

from discord.ext import commands, voice_recv
import discord

from bot import EMBED_COLOR_THEME, socketio, public_url
from bot.core.models import MusicRequest, Source, Song
from bot.core.playback import PlaybackManager
from bot.cogs.assistant import Assistant
from bot.core.events import events, SONG_START, SONG_COMPLETE

log = logging.getLogger(__name__)


class Music(commands.Cog):
    IDLE_TIMEOUT_INTERVAL = 120

    def __init__(self, client):
        # Convert newline endings in the cookies file
        try:
            with open("bot/secrets/cookies.txt", "r") as f:
                cookies_data = f.read()

            cookies_data = (
                cookies_data.replace("\r\n", "\n")
                .replace("\r", "\n")
                .replace("\n", os.linesep)
            )

            with open("bot/secrets/cookies.txt", "w", newline="") as f:
                f.write(cookies_data)
        except Exception as e:
            log.error(f"Failed to convert newline endings in cookies: {e}")

        self.client: discord.Client = client
        self.playback_manager: PlaybackManager = None
        self.voice_client: discord.VoiceProtocol = None

        # Register event listeners
        events.on(SONG_START, self.on_song_start)
        events.on(SONG_COMPLETE, self.on_song_complete)

        self.load_handlers()
        self.reset()

    def reset(self):
        """Resets the state of the bot."""

        # Bot state
        self.ctx = None
        self._timeout_task = None

    def is_connected():
        async def predicate(ctx: commands.Context):
            connected = ctx.voice_client is not None
            # The help command utility skips commands for which the predicate check fails.
            # Hence, it is best not to send any messages here to avoid needless repetitive spam
            # if not connected:
            #     await ctx.send(f'The bot must be in a voice channel for this command to work!')
            return connected

        return commands.check(predicate)

    def load_handlers(self):
        @socketio.on("playback_track_request")
        def handle_track_request(json=None):
            task = self.client.loop.create_task(
                self.play(
                    MusicRequest(
                        query=json["query"],
                        author=self.client.user,
                        ctx=self.ctx,
                        source=Source.WEB,
                    )
                )
            )
            task.add_done_callback(lambda _: on_handle_complete())

        @socketio.on("playback_instruct_play")
        def handle_play(json=None):
            # Create an async task to play/pause the current track
            is_playing = self.ctx.voice_client.is_playing()
            if is_playing:
                self.pause(self.ctx)
            else:
                self.resume(self.ctx)
            on_handle_complete()

        @socketio.on("playback_instruct_skip")
        def handle_skip(json=None):
            # Create an async task to skip the current track
            self.skip(self.ctx)
            on_handle_complete()

        @socketio.on("playback_instruct_loop")
        def handle_loop(json=None):
            # Create an async task to loop the current track
            self.loop()
            on_handle_complete({"is_looping": self.playback_manager.looping})

        def on_handle_complete(data=None):
            socketio.emit("playback_instruct_done", data)

    @commands.command(aliases=["connect"])
    async def join(self, ctx: commands.Context):
        self.ctx = ctx
        await self.join_vc(ctx)

    async def join_vc(self, ctx: commands.Context, voice_channel=None, author=None):
        """
        Instructs the bot to join the voice channel. If voice_channel and author
        are not provided, they will be taken from the context instead.
        """

        if voice_channel is None and ctx.author.voice is None:
            await ctx.send("⚠️\tPlease join a voice channel.")

        # Load auto-play tracks when the bot connects
        voice_channel = voice_channel or ctx.author.voice.channel
        ctx.author = author or ctx.author

        if ctx.voice_client is None:
            try:
                await voice_channel.connect(cls=voice_recv.VoiceRecvClient)
                # await voice_channel.connect()
                if public_url:
                    await ctx.send(
                        f"😊\tCheck out {public_url}/dashboard to manage me!"
                    )

                # Prepare assistant
                assistant_base: Assistant = self.client.get_cog("Assistant")
                if not assistant_base.enabled:
                    # Enable the assistant
                    assistant_connected = assistant_base.enable(ctx)

                    # Let the user know at least once if voice commands are enabled or not
                    if assistant_connected:
                        await ctx.send(f"Hey there! I can take voice commands too.")

                # Initialize PlaybackManager
                self.playback_manager = PlaybackManager(self.client, ctx.voice_client)
            except asyncio.TimeoutError as e:
                await ctx.send(
                    f"❗\tConnection timed out. Please try again later.\n```{e}```"
                )
            except Exception as e:
                await ctx.send(
                    f"❗\tThere was an error trying to join the call.\n```{e}```"
                )
        else:
            await ctx.voice_client.move_to(voice_channel)

        # Cache context
        self.ctx = ctx
        self.voice_client = ctx.voice_client
        await self.start_timeout_timer()

    @commands.command(aliases=["leave", "quit", "bye"])
    @is_connected()
    async def disconnect(self, ctx: commands.Context):
        self.playback_manager.stop()
        assistant_base = self.client.get_cog("Assistant")
        assistant_base.disable(ctx)

        source = await discord.FFmpegOpusAudio.from_probe(
            "bot/resources/sounds/bard.disconnect.ogg"
        )

        def after_callback(error):
            coro = ctx.voice_client.disconnect()
            fut = asyncio.run_coroutine_threadsafe(coro, self.client.loop)
            try:
                fut.result()
            except:
                pass

        # Only play the disconnect track if the bot is still live
        if ctx.voice_client:
            ctx.voice_client.play(source, after=after_callback)

        socketio.start_background_task(socketio.emit, "playback_stop")
        log.info("Disconnected...")

    def on_song_complete(self, song: Song):
        self.start_timeout_timer()

    def on_song_start(self, song: Song):
        socketio.emit(
            "playing_track",
            {
                "title": song.title,
                "thumbnail": song.thumbnail,
                "requester": song.requester.display_name,
                "webpage_url": song.webpage,
                "queue": Music.simplify_queue(self.playback_manager.queue),
            },
        )

        self._timeout_task.cancel()
        task = self.client.loop.create_task(self.send_song_dtls(song))
        try:
            task.result()
        except:
            pass

    @commands.command(aliases=["playing", "nowplaying"])
    @is_connected()
    async def now(self, ctx):
        await self.send_song_dtls(ctx)

    async def send_song_dtls(self, song: Song = None, ctx: commands.Context = None):
        if ctx is None:
            ctx = self.ctx

        if song is None:
            song = self.playback_manager.now()

        requester = song.requester
        footer_text = (
            f"Played automatically by me. This song will be skipped as soon as you play something else!"
            if song.requester == self.client.user
            else f"Song requested by {requester.display_name}"
        )

        embed = discord.Embed.from_dict(
            {
                "title": song.title,
                "description": f"[Link to video]({song.webpage})",
                "thumbnail": {
                    "url": song.thumbnail,
                },
                "color": 15844367,
                "fields": [
                    {
                        "name": "Duration",
                        "value": song.duration,
                        "inline": True,
                    },
                    {
                        "name": "Loop",
                        "value": "Yes" if self.playback_manager.looping else "No",
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

    async def play(self, request: MusicRequest):
        ctx = request.ctx

        # Qualify the message object of the request
        if request.source == Source.WEB:
            msg = await ctx.send(f'Received on the web player: "{request.query}".')
            request.msg = msg
        else:
            request.msg = ctx.message

        results = self.playback_manager.search_and_add(request)

        if len(results) == 1:
            await ctx.send(f"✅\tQueued {results[0].title}")
        elif len(results) > 1:
            await ctx.send(f"✅\tQueued {len(results)} tracks")
        else:
            # Return if no tracks were found
            await ctx.send(f'No results for "{request.query}" were found.')
            return

        # Submitting analytics
        for song in results:
            self.client.get_cog("Analytics").submit_track(
                request.msg.id,
                request.msg.channel.id,
                request.msg.guild.id,
                song.title,
                request.author.id,
                request.msg.created_at,
            )

        await self.playback_manager.play()
        socketio.emit(
            "playlist_update",
            {"queue": Music.simplify_queue(list(self.playback_manager.queue))},
        )

    @commands.command(name="play")
    async def play_command(self, ctx: commands.Context, *, query: str = None):
        try:
            await self.join_vc(ctx)

            if ctx.voice_client is not None and self.playback_manager is None:
                await ctx.send(
                    "🛑\tPlease do **not** spam commands until I join the call. "
                    "Your request was ignored. Submit it again once I've connected."
                )
                return

            await ctx.send(
                "🔎\tSearching..." if query else "🎲\tPlaying a random song..."
            )
            await self.play(MusicRequest(query, ctx.author, self.ctx, Source.CMD))
        except ConnectionError:
            ctx.send("Please join a voice channel")

    @staticmethod
    def simplify_queue(queue: list[Song]):
        return [
            {
                "title": song.title,
                "thumbnail": song.thumbnail,
                "duration": song.duration,
            }
            for song in queue
        ]

    async def start_timeout_timer(self):
        if self._timeout_task:
            self._timeout_task.cancel()
        self._timeout_task = self.client.loop.create_task(self.idle_timeout())

    async def idle_timeout(self):
        await asyncio.sleep(Music.IDLE_TIMEOUT_INTERVAL)

        try:
            voice_client = self.ctx.voice_client
            alone = (
                voice_client
                and len(voice_client.channel.members) == 1
                and voice_client.channel.members[0].id == self.client.user.id
            )
            idle = len(self.playback_manager.queue) == 0

            if alone or idle:
                await self.ctx.send("👋\tSee you later!")

                # It is necessary to pass all required arguments to the function in order for it to execute
                # Calling self.disconnect() alone without any parameters does not actually invoke the function
                # This could be because of some pre-processing done by the decorators attached.
                await self.disconnect(self.ctx)
        except:
            pass

    def loop(self):
        self.playback_manager.loop()
        socketio.emit("playback_state", {"looping": self.playback_manager.looping})

    @commands.group(name="loop", invoke_without_command=True)
    @is_connected()
    async def _loop(self, ctx: commands.Context):
        self.loop()
        await ctx.send(
            f'{"Looping" if self.playback_manager.looping else "Stopped looping"}'
        )

    @_loop.command(name="queue", aliases=["all"])
    @is_connected()
    async def loop_queue(self, ctx: commands.Context):
        self.playback_manager.loop_queue()
        await ctx.send(
            f'{"Looping queue from current track" if self.playback_manager.looping_queue else "Stopped looping queue"}'
        )

    @commands.command(name="queue", aliases=["q"])
    @is_connected()
    async def show_queue(self, ctx: commands.Context):
        song_count = len(self.playback_manager.queue)
        description = f"{song_count} song(s) queued."
        small_queue = list(itertools.islice(self.playback_manager.queue, 0, 10))
        if song_count > 10:
            description += " Showing the first ten songs."

        embed = discord.Embed.from_dict(
            {
                "title": f'Bard\'s Queue{" (Looping)" if self.playback_manager.looping_queue else ""}',
                "description": description,
                "color": EMBED_COLOR_THEME,
                "fields": [
                    {
                        "name": f"{i + 1}. {song.title}",
                        "value": song.duration,
                        "inline": False,
                    }
                    for i, song in enumerate(small_queue)
                ],
            }
        )

        await ctx.send(embed=embed)

    def skip(self, ctx: commands.Context, count: int = 1):
        self.playback_manager.skip(count)

    @commands.command(name="skip")
    @is_connected()
    async def _skip(self, ctx: commands.Context, count: int = 1):
        self.skip(ctx, count)

    @commands.command()
    @is_connected()
    async def remove(self, ctx: commands.Context, index):
        self.playback_manager.remove(index)

    def pause(self, ctx: commands.Context):
        self.playback_manager.pause()
        socketio.emit("playback_state", {"playing": ctx.voice_client.is_playing()})

    @commands.command(name="pause")
    @is_connected()
    async def _pause(self, ctx: commands.Context):
        self.pause(ctx)

    async def suspend(self, ctx: commands.Context):
        self.playback_manager.suspend()

    def resume(self, ctx: commands.Context):
        self.playback_manager.resume()
        socketio.emit("playback_state", {"playing": ctx.voice_client.is_playing()})

    @commands.command(name="resume")
    @is_connected()
    async def _resume(self, ctx: commands.Context):
        self.resume(ctx)

    def remove_suspension(self):
        self.playback_manager.remove_suspension()

    def is_playback_paused(self):
        return not self.playback_manager.playback_enabled.is_set()


async def setup(client):
    await client.add_cog(Music(client))
