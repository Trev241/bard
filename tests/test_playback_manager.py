import asyncio
from collections import deque
from types import SimpleNamespace

from bot.core.models import Song
from bot.core.playback import PlaybackManager


class FakeVoiceClient:
    def __init__(self):
        self.stop_count = 0
        self.paused = False
        self.playing = False

    def stop_playing(self):
        self.stop_count += 1

    def pause(self):
        self.paused = True

    def resume(self):
        self.paused = False

    def is_playing(self):
        return self.playing

    def is_paused(self):
        return self.paused


def make_song(title, requester=None):
    return Song(
        title=title,
        duration="0:03:00",
        requester=requester or SimpleNamespace(display_name="tester"),
        ie_result={},
    )


def make_manager(*songs):
    manager = PlaybackManager.__new__(PlaybackManager)
    manager.queue = deque(songs)
    manager.voice_client = FakeVoiceClient()
    manager.client = SimpleNamespace(user=SimpleNamespace(display_name="Bard"))
    manager.curr_song = songs[0] if songs else None
    manager.idle = not bool(songs)
    manager.looping = False
    manager.skip_songs = 0
    manager.looping_queue = False
    manager.playback_enabled = asyncio.Event()
    manager.playback_enabled.set()
    manager.force_skip = False
    manager.curr_song_start_time = 0
    manager.auto_play = False
    manager.auto_play_songs = None
    return manager


def test_add_appends_song():
    manager = make_manager()
    song = make_song("Track A")

    manager.add(song)

    assert list(manager.queue) == [song]


def test_skip_stops_voice_and_records_count():
    manager = make_manager(make_song("Track A"), make_song("Track B"))

    manager.skip(2)

    assert manager.voice_client.stop_count == 1
    assert manager.skip_songs == 2


def test_remove_queued_song_by_one_based_index():
    first = make_song("Track A")
    second = make_song("Track B")
    manager = make_manager(first, second)

    removed = manager.remove(2)

    assert removed == second
    assert list(manager.queue) == [first]


def test_remove_current_song_skips():
    first = make_song("Track A")
    second = make_song("Track B")
    manager = make_manager(first, second)

    removed = manager.remove(1)

    assert removed is None
    assert manager.voice_client.stop_count == 1
    assert manager.skip_songs == 1
    assert list(manager.queue) == [first, second]


def test_loop_toggles_current_track_looping():
    manager = make_manager(make_song("Track A"))

    manager.loop()
    assert manager.looping is True

    manager.loop()
    assert manager.looping is False


def test_loop_queue_toggles_queue_looping():
    manager = make_manager(make_song("Track A"))

    manager.loop_queue()
    assert manager.looping_queue is True

    manager.loop_queue()
    assert manager.looping_queue is False


def test_pause_and_resume_delegate_to_voice_client():
    manager = make_manager(make_song("Track A"))

    manager.pause()
    assert manager.voice_client.paused is True

    manager.resume()
    assert manager.voice_client.paused is False

