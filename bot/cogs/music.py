import asyncio
import itertools
import logging

import discord
from discord.ext import commands, voice_recv

from bot import EMBED_COLOR_THEME, config, public_url, socketio
from bot.core.events import SONG_COMPLETE, SONG_START, events
from bot.core.exceptions import (
    AlreadyConnected,
    AlreadyConnecting,
    CannotCompleteAction,
    ConnectionNotReady,
    UserNotInVoice,
)
from bot.core.music_service import MusicService, QueueOutcome
from bot.core.models import MusicRequest, Song, Source
from bot.core.playback import PlaybackManager

# from bot.cogs.assistant import Assistant

log = logging.getLogger(__name__)


class Music(commands.Cog):
    IDLE_TIMEOUT_INTERVAL = 120

    VOICE_DISCONNECTED = "DISCONNECTED"
    VOICE_DISCONNECTING = "DISCONNECTING"
    VOICE_CONNECTED = "CONNECTED"
    VOICE_CONNECTING = "CONNECTING"

    def __init__(self, client):
        self.client: discord.Client = client
        self.playback_manager: PlaybackManager = None
        self.service = MusicService(client)
        self.voice_client: discord.VoiceProtocol = None
        self.voice_state = Music.VOICE_DISCONNECTED

        events.on(SONG_START, self.on_song_start)
        events.on(SONG_COMPLETE, self.on_song_complete)

        self.load_handlers()
        self.reset()

    def reset(self):
        timeout_task = getattr(self, "_timeout_task", None)
        if timeout_task:
            timeout_task.cancel()

        self.ctx = None
        self.playback_manager = None
        self.service.detach_playback()
        self.voice_client = None
        self.voice_state = Music.VOICE_DISCONNECTED
        self._timeout_task = None

    def cog_unload(self):
        events.off(SONG_START, self.on_song_start)
        events.off(SONG_COMPLETE, self.on_song_complete)
        timeout_task = getattr(self, "_timeout_task", None)
        if timeout_task:
            timeout_task.cancel()

    def is_connected():
        async def predicate(ctx: commands.Context):
            return ctx.voice_client is not None

        return commands.check(predicate)

    def load_handlers(self):
        @socketio.on("playback_track_request")
        def handle_track_request(json=None):
            if not self.is_ready_for_web_controls():
                socketio.emit("playback_instruct_done", {"error": "not_connected"})
                return

            query = (json or {}).get("query")
            if not query or not query.strip():
                socketio.emit("playback_instruct_done", {"error": "empty_query"})
                return

            task = self.client.loop.create_task(
                self.play(
                    MusicRequest(
                        query=query.strip(),
                        author=self.client.user,
                        ctx=self.ctx,
                        source=Source.WEB,
                    )
                )
            )
            task.add_done_callback(self._socket_task_done)

        @socketio.on("playback_instruct_play")
        def handle_play(json=None):
            if not self.is_ready_for_web_controls():
                on_handle_complete({"error": "not_connected"})
                return

            is_playing = self.ctx.voice_client.is_playing()
            if is_playing:
                self.pause(self.ctx)
            else:
                self.resume(self.ctx)
            on_handle_complete()

        @socketio.on("playback_instruct_skip")
        def handle_skip(json=None):
            if not self.is_ready_for_web_controls():
                on_handle_complete({"error": "not_connected"})
                return

            self.skip(self.ctx)
            on_handle_complete()

        @socketio.on("playback_instruct_loop")
        def handle_loop(json=None):
            if not self.is_ready_for_web_controls():
                on_handle_complete({"error": "not_connected"})
                return

            self.loop()
            on_handle_complete({"is_looping": self.service.is_looping()})

        def on_handle_complete(data=None):
            socketio.emit("playback_instruct_done", data)

    @staticmethod
    def _log_task_exception(task):
        try:
            task.result()
        except Exception:
            log.warning("Background music task failed.", exc_info=True)

    def _socket_task_done(self, task):
        self._log_task_exception(task)
        socketio.emit("playback_instruct_done")

    def is_ready_for_web_controls(self):
        return (
            self.voice_state == Music.VOICE_CONNECTED
            and self.ctx is not None
            and self.playback_manager is not None
        )

    @commands.command(name="join", aliases=["connect"])
    async def _join(self, ctx: commands.Context):
        await self.join(ctx)

    async def join(self, ctx: commands.Context, voice_channel=None, author=None):
        """
        Instructs the bot to join the voice channel. If `voice_channel` and `author`
        are not provided, they will be taken from the context instead.
        """

        if voice_channel is None and ctx.author.voice is None:
            raise UserNotInVoice("User not in a voice channel.")

        if self.voice_state == Music.VOICE_CONNECTED:
            raise AlreadyConnected("Already connected to voice.")

        if self.voice_state == Music.VOICE_CONNECTING:
            raise AlreadyConnecting("Already attempting to connect to voice.")

        if self.voice_state == Music.VOICE_DISCONNECTING:
            raise CannotCompleteAction("Still disconnecting from voice.")

        try:
            self.voice_state = Music.VOICE_CONNECTING
            voice_channel = voice_channel or ctx.author.voice.channel
            ctx.author = author or ctx.author

            await voice_channel.connect(cls=voice_recv.VoiceRecvClient, reconnect=False)

            if public_url:
                await ctx.send(f"Check out {public_url}/dashboard to manage me!")

            # try:
            #     assistant_base: Assistant = self.client.get_cog("Assistant")
            #     assistant_connected = assistant_base.enable(ctx)
            #     if assistant_connected:
            #         await ctx.send('Say "OK, Bard" if you need help!')
            # except Exception as e:
            #     # Handle this exception so that the bot can still connect.
            #     log.warning(f"Failed to enable assistant: {e}")

            self.playback_manager = PlaybackManager(self.client, ctx.voice_client)
            self.service.attach_playback(self.playback_manager)
        except Exception:
            self.voice_state = Music.VOICE_DISCONNECTED
            log.exception("Failed to join voice channel.")
            raise

        self.ctx = ctx
        self.voice_client = ctx.voice_client
        self.voice_state = Music.VOICE_CONNECTED
        await self.start_timeout_timer()

    @commands.command(aliases=["leave", "quit", "bye"])
    @is_connected()
    async def disconnect(self, ctx: commands.Context):
        if (
            self.voice_state == Music.VOICE_DISCONNECTED
            or self.voice_state == Music.VOICE_DISCONNECTING
        ):
            return

        self.voice_state = Music.VOICE_DISCONNECTING

        self.service.stop()
        # assistant_base: Assistant = self.client.get_cog("Assistant")
        # assistant_base.disable(ctx)

        voice_client = ctx.voice_client

        async def finish_disconnect():
            try:
                if voice_client and voice_client.is_connected():
                    await voice_client.disconnect()
            except Exception:
                log.warning("Failed to disconnect voice client.", exc_info=True)
            finally:
                self.reset()

        def after_callback(error):
            if error:
                log.warning("Disconnect sound failed: %s", error)

            coro = finish_disconnect()
            fut = asyncio.run_coroutine_threadsafe(coro, self.client.loop)
            try:
                fut.result()
            except Exception:
                log.warning("Failed to disconnect after playback.", exc_info=True)

        try:
            source = await discord.FFmpegOpusAudio.from_probe(config.DISCONNECT_SOUND)
            if voice_client:
                voice_client.play(source, after=after_callback)
            else:
                await finish_disconnect()
        except Exception:
            log.warning("Disconnect sound could not be played.", exc_info=True)
            await finish_disconnect()

        socketio.start_background_task(socketio.emit, "playback_stop")

    def on_song_complete(self, song: Song):
        task = self.client.loop.create_task(self.start_timeout_timer())
        task.add_done_callback(self._log_task_exception)

    def on_song_start(self, song: Song):
        socketio.emit(
            "playing_track",
            {
                "title": song.title,
                "thumbnail": song.thumbnail,
                "requester": song.requester.display_name,
                "webpage_url": song.webpage,
                "queue": Music.simplify_queue(self.service.queue()),
            },
        )

        if self._timeout_task:
            self._timeout_task.cancel()

        task = self.client.loop.create_task(self.send_song_dtls(song))
        task.add_done_callback(self._log_task_exception)

    @commands.command(aliases=["playing", "nowplaying"])
    @is_connected()
    async def now(self, ctx):
        await self.send_song_dtls(ctx=ctx)

    async def send_song_dtls(self, song: Song = None, ctx: commands.Context = None):
        if ctx is None:
            ctx = self.ctx

        if song is None:
            song = self.service.now()

        if song is None:
            await ctx.send("Nothing is playing right now.")
            return

        requester = song.requester
        footer_text = (
            "Played automatically by me. This song will be skipped as soon as you play something else!"
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
                        "value": "Yes" if self.service.is_looping() else "No",
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

        if self.voice_state != Music.VOICE_CONNECTED:
            raise ConnectionNotReady("Voice connection is not ready")

        if request.source == Source.WEB:
            request.msg = await ctx.send(
                f'Received on the web player: "{request.query}".'
            )
        else:
            request.msg = ctx.message

        result = await self.service.request_tracks(request)

        reply_target = request.msg or getattr(ctx, "message", None)

        if result.outcome == QueueOutcome.RANDOM:
            await reply_target.reply("Playing a random song.")
        elif result.outcome == QueueOutcome.NO_RESULTS:
            await reply_target.reply(f'No results for "{request.query}" were found.')
            return
        else:
            reply_msg = (
                f"Queued {result.songs[0].title}"
                if len(result.songs) == 1
                else f"Queued {len(result.songs)} tracks"
            )
            await reply_target.reply(reply_msg)

        socketio.emit(
            "playlist_update",
            {"queue": Music.simplify_queue(list(self.service.queue()))},
        )

    @commands.command(name="play")
    async def play_command(self, ctx: commands.Context, *, query: str = None):
        if query is not None:
            query = query.strip()

        if self.voice_state == Music.VOICE_DISCONNECTED:
            await self.join(ctx)

        self.ctx = ctx
        await ctx.send("Searching...")
        await self.play(MusicRequest(query, ctx.author, self.ctx, Source.CMD))

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
            idle = (
                len(self.service.queue()) == 0
                or not self.service.is_playing()
                or self.service.is_paused()
            )

            if alone or idle:
                await self.ctx.send("See you later!")
                await self.disconnect(self.ctx)
        except Exception:
            log.warning("Idle timeout check failed.", exc_info=True)

    def loop(self):
        looping = self.service.toggle_loop()
        socketio.emit("playback_state", {"looping": looping})

    @commands.group(name="loop", invoke_without_command=True)
    @is_connected()
    async def _loop(self, ctx: commands.Context):
        self.loop()
        looping = self.service.is_looping()
        await ctx.message.reply(
            f'{"Looping" if looping else "Stopped looping"}'
        )

    @_loop.command(name="queue", aliases=["all"])
    @is_connected()
    async def loop_queue(self, ctx: commands.Context):
        looping_queue = self.service.toggle_queue_loop()
        await ctx.message.reply(
            f'{"Looping queue from current track" if looping_queue else "Stopped looping queue"}'
        )

    @commands.command(name="queue", aliases=["q"])
    @is_connected()
    async def show_queue(self, ctx: commands.Context):
        queue = self.service.queue()
        song_count = len(queue)
        description = f"{song_count} song(s) queued."
        small_queue = list(itertools.islice(queue, 0, 10))
        if song_count > 10:
            description += " Showing the first ten songs."

        embed = discord.Embed.from_dict(
            {
                "title": f'Bard\'s Queue{" (Looping)" if self.service.is_looping_queue() else ""}',
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
        count = max(1, count)
        self.service.skip(count)

    @commands.command(name="skip")
    @is_connected()
    async def _skip(self, ctx: commands.Context, count: int = 1):
        self.skip(ctx, count)

    @commands.command()
    @is_connected()
    async def remove(self, ctx: commands.Context, index: int):
        removed = self.service.remove(index)
        if removed:
            await ctx.message.reply(f"Removed {removed.title}.")
        elif index == 1:
            await ctx.message.reply("Skipping the current track.")
        else:
            await ctx.message.reply("That queue index does not exist.")

    def pause(self, ctx: commands.Context):
        self.service.pause()
        socketio.emit("playback_state", {"playing": ctx.voice_client.is_playing()})

    @commands.command(name="pause")
    @is_connected()
    async def _pause(self, ctx: commands.Context):
        self.pause(ctx)

    async def suspend(self, ctx: commands.Context):
        self.service.suspend()

    def resume(self, ctx: commands.Context):
        self.service.resume()
        socketio.emit("playback_state", {"playing": ctx.voice_client.is_playing()})

    @commands.command(name="resume")
    @is_connected()
    async def _resume(self, ctx: commands.Context):
        self.resume(ctx)

    def remove_suspension(self):
        self.service.remove_suspension()

    def is_playback_paused(self):
        return self.service.is_flow_paused()


async def setup(client):
    await client.add_cog(Music(client))
