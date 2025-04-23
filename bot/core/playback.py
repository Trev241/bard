import logging
import asyncio
import random
import json
import copy
import time
from collections import deque
from datetime import timedelta

import yt_dlp
import validators
from discord import FFmpegOpusAudio
from discord import Client
from discord.ext.voice_recv import VoiceRecvClient

from bot.core.models import MusicRequest, Song
from bot.core.events import events, SONG_START

logger = logging.getLogger(__name__)


class PlaybackManager:
    def __init__(self, client: Client, voice_client: VoiceRecvClient):
        YDL_LOGGER = logging.getLogger("yt-dlp")
        YDL_LOGGER.setLevel(logging.DEBUG)
        YDL_LOG_HANDLER = logging.StreamHandler()
        YDL_LOGGER.addHandler(YDL_LOG_HANDLER)

        YDL_OPTIONS = {
            "format": "bestaudio",
            "cookiefile": "bot/secrets/cookies.txt",
            "verbose": False,
            "quiet": False,
            "logger": YDL_LOGGER,
        }

        self.ffmpeg_options = {
            "before_options": "-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5",
            "options": "-vn",
        }

        self.auto_playlist_url = (
            "https://www.youtube.com/playlist?list=PL7Akty-aEXMq8x9ToQy7v4TxLsi42MHSd"
        )

        # Core
        self.yt = yt_dlp.YoutubeDL(YDL_OPTIONS)
        self.queue: deque[Song] = deque()
        self.voice_client = voice_client
        self.client = client
        self.curr_song = None

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
        self.auto_play_songs = None

    def search(self, request: MusicRequest, auto_play: bool = False) -> list[Song]:
        if request.query is None:
            return None

        info = self.yt.extract_info(
            (
                request.query
                if validators.url(request.query)
                else f"ytsearch:{request.query}"
            ),
            download=False,
            process=False,
        )

        entries = info["entries"] if info.get("_type", None) == "playlist" else [info]
        results = []
        for entry in entries:
            with open("bot/resources/dumps/entries.json", "w") as fp:
                json.dump(self.yt.sanitize_info(entry), fp)

            try:
                thumbnails = entry.get("thumbnails", [])
                if len(thumbnails) > 0 and "url" in thumbnails[-1]:
                    thumbnail_url = thumbnails[-1]["url"]
                else:
                    thumbnail_url = "/static/placeholder.png"

                song = Song(
                    title=entry.get("title", "Unknown title"),
                    duration=str(
                        timedelta(
                            seconds=entry.get("duration", 0),
                        )
                    ),
                    requester=request.author,
                    ie_result=entry,
                    auto_play=auto_play,
                    thumbnail=thumbnail_url,
                )
                results.append(song)
            except:
                logger.warning(
                    f"Failed to process entry - {entry['title']}. This entry will be skipped."
                )

        return results

    def search_and_add(self, request: MusicRequest) -> list[Song]:
        songs = self.search(request)

        if songs is None:
            self.add()
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
            # Add a random song
            if self.auto_play_songs is None or len(self.auto_play_songs) == 0:
                # Prepare the auto-play list if its empty or does not exist
                songs = self.search(
                    MusicRequest(
                        self.auto_playlist_url,
                        self.client.user,
                    ),
                    auto_play=True,
                )
                random.shuffle(songs)
                self.auto_play_songs = deque(songs)

            song = self.auto_play_songs.popleft()

        self.queue.append(song)

    def after_playback(self, error):
        """
        Callback for when playback completes, either naturally or when
        skipped by the user
        """

        if error:
            raise error

        if not self.looping or self.skip_songs > 0 or self.force_skip:
            skip_count = min(max(1, self.skip_songs), len(self.queue))

            for _ in range(skip_count):
                song = self.queue.popleft()

                if self.looping_queue:
                    self.add(song)
        elif self.looping:
            self.queue[0].start_at = 0

        if self.auto_play and len(self.queue) == 0:
            self.add()  # Add a random song if auto-play is enabled

        if len(self.queue) > 0:
            # Base case - no more tracks to play
            coro_next = self.next()
            future = asyncio.run_coroutine_threadsafe(coro_next, self.client.loop)

            try:
                future.result()
            except:
                pass

        self.skip_songs = 0
        self.force_skip = False

    async def next(self):
        """
        Plays the next song available at the start of the queue
        """

        if len(self.queue) == 0:
            # Edge case for when next is called on an empty queue
            self.after_playback()
            return

        song = self.queue[0]

        if not song.url or not song.thumbnail or not song.webpage:
            # Only process if at least one property is missing
            info = self.yt.process_ie_result(song.ie_result, download=False)
            song.thumbnail = info["thumbnails"][-1]["url"]
            song.webpage = info["webpage_url"]
            format: dict = next(
                (
                    format
                    for format in info["formats"]
                    if info["format_id"] == format["format_id"]
                ),
                None,
            )
            song.url = format.get("url")

            with open("bot/resources/dumps/yt-dlp.json", "w") as fp:
                json.dump(self.yt.sanitize_info(info), fp, indent=2)

        # Wait if playback is suspended
        await self.playback_enabled.wait()

        self.curr_song = song
        ffmpeg_options = self.ffmpeg_options.copy()
        ffmpeg_options["options"] += f" -ss {song.start_at}"
        audio = await FFmpegOpusAudio.from_probe(song.url, **ffmpeg_options)
        self.voice_client.play(audio, after=self.after_playback)

        # Emit event
        events.emit(SONG_START, song=song)

        # Save the timestamp at which this track started
        self.curr_song_start_time = time.time() - song.start_at

    def stop(self):
        """
        Stops playback completely
        """

        self.queue.clear()
        self.curr_song = None
        self.looping = self.auto_play = False
        self.voice_client.stop_playing()

    async def play(self):
        if not self.is_playing():
            await self.next()
        elif self.curr_song.auto_play:
            self.skip()

    def skip(self, count: int = 1):
        self.voice_client.stop_playing()
        self.skip_songs = count

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
