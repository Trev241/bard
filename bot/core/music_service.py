from dataclasses import dataclass, field
from enum import Enum

from bot.core.exceptions import ConnectionNotReady
from bot.core.models import MusicRequest, Song
from bot.core.playback import PlaybackManager


class QueueOutcome(Enum):
    RANDOM = "random"
    NO_RESULTS = "no_results"
    QUEUED = "queued"


@dataclass
class QueueResult:
    outcome: QueueOutcome
    songs: list[Song] = field(default_factory=list)


class MusicService:
    def __init__(self, client, playback_manager: PlaybackManager = None):
        self.client = client
        self.playback_manager = playback_manager

    def attach_playback(self, playback_manager: PlaybackManager):
        self.playback_manager = playback_manager

    def detach_playback(self):
        self.playback_manager = None

    def require_playback(self) -> PlaybackManager:
        if not self.playback_manager:
            raise ConnectionNotReady("Voice connection is not ready")

        return self.playback_manager

    def has_playback(self):
        return self.playback_manager is not None

    async def request_tracks(self, request: MusicRequest) -> QueueResult:
        playback = self.require_playback()
        songs = playback.search_and_add(request)

        if songs is None:
            result = QueueResult(QueueOutcome.RANDOM)
        elif len(songs) == 0:
            return QueueResult(QueueOutcome.NO_RESULTS)
        else:
            result = QueueResult(QueueOutcome.QUEUED, songs)

        await playback.play()
        return result

    def now(self) -> Song:
        return self.require_playback().now()

    def queue(self):
        return self.require_playback().queue

    def stop(self):
        self.require_playback().stop()

    def skip(self, count: int = 1):
        self.require_playback().skip(count)

    def remove(self, index):
        return self.require_playback().remove(index)

    def pause(self):
        self.require_playback().pause()

    def resume(self):
        self.require_playback().resume()

    def toggle_loop(self):
        playback = self.require_playback()
        playback.loop()
        return playback.looping

    def toggle_queue_loop(self):
        playback = self.require_playback()
        playback.loop_queue()
        return playback.looping_queue

    def suspend(self):
        self.require_playback().suspend()

    def remove_suspension(self):
        self.require_playback().remove_suspension()

    def is_playing(self):
        return self.require_playback().is_playing()

    def is_paused(self):
        return self.require_playback().is_paused()

    def is_flow_paused(self):
        return not self.require_playback().playback_enabled.is_set()

    def is_looping(self):
        return self.require_playback().looping

    def is_looping_queue(self):
        return self.require_playback().looping_queue
