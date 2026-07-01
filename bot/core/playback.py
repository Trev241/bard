from collections import deque
import logging
import asyncio
import copy
import time

from discord import FFmpegOpusAudio
from discord import Client
from discord import VoiceProtocol

from bot.core.models import MusicRequest, Song
from bot.core.events import SONG_COMPLETE, SONG_START, events
from bot.core.resolver import TrackResolver

logger = logging.getLogger(__name__)


class PlaybackManager:
    def __init__(
        self,
        client: Client,
        voice_client: VoiceProtocol,
        resolver: TrackResolver = None,
    ):
        self.ffmpeg_options = {
            "before_options": "-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5",
            "options": "-vn",
        }

        # Core
        self.resolver = resolver or TrackResolver(client)
        self.queue: deque[Song] = deque()
        self.voice_client = voice_client
        self.client = client
        self.curr_song = None
        self.idle = True
        # An extra flag is needed because is_playing is only set when audio actually
        # starts playing. This creates an edge case where two songs can be queued to
        # play at the same time if requested in quick succession.

        # Playback controls
        self.looping = False
        self.skip_songs = 0
        self.looping_queue = False

        # Playback suspension
        self.playback_enabled = asyncio.Event()
        self.playback_enabled.set()
        self.force_skip = False
        self.curr_song_start_time = 0

        # Auto-play properties
        self.auto_play = True
        self._prefetch_tasks = {}

    def search(self, request: MusicRequest, auto_play: bool = False) -> list[Song]:
        return self.resolver.search(request, auto_play)

    def search_and_add(self, request: MusicRequest) -> list[Song]:
        songs = self.search(request)

        if songs is None:
            try:
                self.add()
            except Exception:
                logger.warning("Failed to add autoplay track.", exc_info=True)
                return []
        else:
            for song in songs:
                self.add(song)

        return songs

    def add(self, song: Song = None):
        """
        Adds a song to the queue. If song is `None`
        or not given, a random song is added to the queue.
        """

        if song is None:
            song = self.resolver.next_autoplay_song()

        self.queue.append(song)

    def after_playback(self, error):
        """
        Callback for when playback completes, either naturally or when
        skipped by the user
        """

        playback_failed = error is not None
        if playback_failed:
            failed_song = self.queue[0] if self.queue else self.curr_song
            exc_info = (
                (type(error), error, error.__traceback__)
                if isinstance(error, BaseException)
                else False
            )
            logger.warning(
                "Playback callback reported an error for %s.",
                failed_song.title if failed_song else "unknown track",
                exc_info=exc_info,
            )

        if playback_failed or not self.looping or self.skip_songs > 0 or self.force_skip:
            skip_count = min(max(1, self.skip_songs), len(self.queue))

            for _ in range(skip_count):
                song = self.queue.popleft()
                events.emit(SONG_COMPLETE, song=song)

                if self.looping_queue and not playback_failed:
                    self.add(song)
        elif self.looping:
            events.emit(SONG_COMPLETE, song=self.queue[0])
            self.queue[0].start_at = 0

        if len(self.queue) == 0:
            if self.auto_play:
                try:
                    self.add()  # Add a random song if auto-play is enabled
                except Exception:
                    logger.warning("Failed to add autoplay track.", exc_info=True)
                    self.idle = True
            else:
                self.idle = True

        if len(self.queue) > 0:
            # Base case - no more tracks to play
            coro_next = self.next()
            future = asyncio.run_coroutine_threadsafe(coro_next, self.client.loop)

            try:
                future.result()
            except Exception:
                logger.warning("Failed to schedule next track after playback.", exc_info=True)
                pass

        self.skip_songs = 0
        self.force_skip = False

    async def next(self):
        """
        Plays the next song available at the start of the queue
        """

        while self.queue:
            song = self.queue[0]

            try:
                await self.hydrate(song)

                # Wait if playback is suspended
                await self.playback_enabled.wait()

                self.curr_song = song
                ffmpeg_options = self.ffmpeg_options.copy()
                ffmpeg_options["options"] += f" -ss {song.start_at}"
                audio = await self.create_audio_source(song, ffmpeg_options)
                self.voice_client.play(audio, after=self.after_playback)
            except Exception:
                failed_song = self.queue.popleft()
                events.emit(SONG_COMPLETE, song=failed_song)
                logger.warning(
                    "Failed to start playback for %s. Skipping track.",
                    failed_song.title,
                    exc_info=True,
                )
                continue

            # Emit event
            events.emit(SONG_START, song=song)

            # Save the timestamp at which this track started
            self.curr_song_start_time = time.time() - song.start_at
            self.idle = False
            self.prefetch_next_track()
            return

        self.curr_song = None
        self.idle = True

    async def hydrate(self, song: Song):
        self._prefetch_tasks = getattr(self, "_prefetch_tasks", {})
        task = self._prefetch_tasks.pop(id(song), None)
        if task:
            await task
            if song.url:
                return song

        return await asyncio.to_thread(self.resolver.hydrate, song)

    async def create_audio_source(self, song: Song, ffmpeg_options):
        if (song.audio_codec or "").lower() == "opus":
            logger.debug("Starting %s without FFmpeg probe; codec is Opus.", song.title)
            return FFmpegOpusAudio(song.url, codec="copy", **ffmpeg_options)

        logger.debug("Starting %s with FFmpeg probe; codec is %s.", song.title, song.audio_codec)
        return await FFmpegOpusAudio.from_probe(song.url, **ffmpeg_options)

    def prefetch_next_track(self):
        self._prefetch_tasks = getattr(self, "_prefetch_tasks", {})
        if len(self.queue) < 2:
            return

        song = self.queue[1]
        if song.url:
            return

        key = id(song)
        if key in self._prefetch_tasks:
            return

        task = self.client.loop.create_task(self._prefetch_track(song, key))
        self._prefetch_tasks[key] = task

    async def _prefetch_track(self, song: Song, key):
        try:
            await asyncio.to_thread(self.resolver.hydrate, song)
            logger.debug("Prefetched next track: %s.", song.title)
        except Exception:
            logger.debug("Failed to prefetch next track: %s.", song.title, exc_info=True)
        finally:
            self._prefetch_tasks.pop(key, None)

    def stop(self):
        """
        Stops playback completely
        """

        self.queue.clear()
        self.curr_song = None
        self.looping = self.auto_play = False
        self.cancel_prefetch_tasks()
        self.voice_client.stop_playing()
        self.idle = True

    def cancel_prefetch_tasks(self):
        self._prefetch_tasks = getattr(self, "_prefetch_tasks", {})
        for task in self._prefetch_tasks.values():
            task.cancel()
        self._prefetch_tasks.clear()

    async def play(self):
        if self.idle:
            self.idle = False
            await self.next()
        elif self.curr_song and self.curr_song.auto_play:
            self.skip()

    def skip(self, count: int = 1):
        self.skip_songs = count
        self.voice_client.stop_playing()

    def now(self) -> Song:
        return self.curr_song

    def remove(self, index):
        index = int(index) - 1

        if 0 <= index and index < len(self.queue):
            if index == 0:
                self.skip()
            else:
                song = self.queue[index]
                del self.queue[index]
                return song
        else:
            return None

    def loop(self):
        self.looping = not self.looping

    def loop_queue(self):
        self.looping_queue = not self.looping_queue

    def pause(self):
        self.voice_client.pause()

    def resume(self):
        self.voice_client.resume()

    def is_playing(self):
        return self.voice_client.is_playing()

    def is_paused(self):
        return self.voice_client.is_paused()

    def is_connected(self):
        return self.voice_client.is_connected()

    def suspend(self):
        """
        Pauses playback indefinitely by suspending playback flow
        entirely until the suspension is removed.

        Unlike `pause`, `PlaybackManager` also surrenders control
        over `voice_client` allowing it to be used to play audio
        unrelated to `PlaybackManager`.
        """

        if len(self.queue) == 0 or not self.playback_enabled.is_set():
            return

        # Before suspending playback, create a copy of the current track
        # and remember where we left off so that when playback is restored,
        # the original song will appear to resume seamlessly.

        curr_song_copy = copy.copy(self.curr_song)
        curr_song_copy.start_at = int(time.time() - self.curr_song_start_time)
        curr_song_orig = self.queue.popleft()
        self.force_skip = True  # Flag to bypass tracks that are looping
        self.queue.appendleft(curr_song_copy)
        self.queue.appendleft(curr_song_orig)

        self.playback_enabled.clear()
        self.skip()

    def remove_suspension(self):
        self.playback_enabled.set()
