from collections import deque
from datetime import timedelta
import json
import logging
import random

import validators

from bot import config
from bot.core.models import MusicRequest, Song
from bot.core.youtube import create_ytdlp

logger = logging.getLogger(__name__)


class TrackResolver:
    def __init__(self, client, yt=None, autoplay_playlist_url=None):
        self.client = client
        self.yt = yt or create_ytdlp()
        self.autoplay_playlist_url = autoplay_playlist_url or config.AUTOPLAY_PLAYLIST_URL
        self._autoplay_songs = None

    def search(self, request: MusicRequest, auto_play: bool = False) -> list[Song]:
        if request.query is None:
            return None

        try:
            info = self.yt.extract_info(
                (
                    request.query
                    if validators.url(request.query)
                    else f"ytsearch:{request.query}"
                ),
                download=False,
                process=False,
            )
        except Exception:
            logger.warning("yt-dlp search failed for %s.", request.query, exc_info=True)
            return []

        if not info:
            return []

        entries = info.get("entries", []) if info.get("_type") == "playlist" else [info]
        songs = []
        for entry in entries:
            self.dump_entry(entry)

            song = self.song_from_entry(entry, request, auto_play)
            if song:
                songs.append(song)

        return songs

    def dump_entry(self, entry):
        try:
            with open(config.ENTRIES_DUMP, "w") as fp:
                json.dump(self.yt.sanitize_info(entry), fp)
        except OSError:
            logger.debug("Failed to write yt-dlp entry dump.", exc_info=True)

    def song_from_entry(
        self, entry: dict, request: MusicRequest, auto_play: bool = False
    ) -> Song | None:
        if not isinstance(entry, dict):
            logger.debug("Skipping malformed yt-dlp entry: %r", entry)
            return None

        try:
            thumbnails = entry.get("thumbnails", [])
            if len(thumbnails) > 0 and "url" in thumbnails[-1]:
                thumbnail_url = thumbnails[-1]["url"]
            else:
                thumbnail_url = "/static/placeholder.png"

            return Song(
                title=entry.get("title", "Unknown title"),
                duration=str(timedelta(seconds=entry.get("duration", 0))),
                requester=request.author,
                ie_result=entry,
                auto_play=auto_play,
                thumbnail=thumbnail_url,
            )
        except Exception:
            logger.warning(
                "Failed to process entry - %s. This entry will be skipped.",
                entry.get("title", "Unknown title"),
                exc_info=True,
            )

        return None

    def next_autoplay_song(self) -> Song:
        if self._autoplay_songs is None or len(self._autoplay_songs) == 0:
            songs = self.search(
                MusicRequest(self.autoplay_playlist_url, self.client.user),
                auto_play=True,
            )
            if not songs:
                raise ValueError("Autoplay playlist did not return playable tracks.")
            random.shuffle(songs)
            self._autoplay_songs = deque(songs)

        return self._autoplay_songs.popleft()

    def hydrate(self, song: Song) -> Song:
        if song.url and song.thumbnail and song.webpage:
            return song

        info = self.yt.process_ie_result(song.ie_result, download=False)
        thumbnails = info.get("thumbnails") or []
        song.thumbnail = (
            thumbnails[-1].get("url")
            if thumbnails and thumbnails[-1].get("url")
            else song.thumbnail or "/static/placeholder.png"
        )
        song.webpage = info.get("webpage_url") or song.webpage
        formats = info.get("formats", [])
        selected_format = next(
            (fmt for fmt in formats if info.get("format_id") == fmt.get("format_id")),
            None,
        ) or next((fmt for fmt in formats if fmt.get("url")), None)
        song.url = selected_format.get("url") if selected_format else None
        if not song.url:
            raise ValueError(f"No playable format found for {song.title}")

        try:
            with open(config.YTDLP_DUMP, "w") as fp:
                json.dump(self.yt.sanitize_info(info), fp, indent=2)
        except OSError:
            logger.debug("Failed to write hydrated yt-dlp dump.", exc_info=True)

        return song
