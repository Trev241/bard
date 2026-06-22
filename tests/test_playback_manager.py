import asyncio
from collections import deque
from types import SimpleNamespace

import pytest

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
    manager.resolver = SimpleNamespace(hydrate=lambda song: song)
    manager._prefetch_tasks = {}
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


def test_skip_sets_count_before_voice_stop_callback():
    first = make_song("Track A")
    second = make_song("Track B")
    manager = make_manager(first, second)

    def stop_and_callback():
        manager.voice_client.stop_count += 1
        manager.after_playback(None)

    manager.voice_client.stop_playing = stop_and_callback

    manager.skip(2)

    assert list(manager.queue) == []
    assert manager.voice_client.stop_count == 1


def test_after_playback_error_drops_failed_track_without_raising():
    song = make_song("Track A")
    manager = make_manager(song)

    manager.after_playback(RuntimeError("ffmpeg failed"))

    assert list(manager.queue) == []
    assert manager.idle is True


def test_after_playback_error_does_not_requeue_looped_track():
    song = make_song("Track A")
    manager = make_manager(song)
    manager.looping = True
    manager.looping_queue = True

    manager.after_playback(RuntimeError("ffmpeg failed"))

    assert list(manager.queue) == []
    assert manager.idle is True


def test_after_playback_goes_idle_when_autoplay_fails():
    song = make_song("Track A")
    manager = make_manager(song)
    manager.auto_play = True
    manager.resolver = SimpleNamespace(
        hydrate=lambda song: song,
        next_autoplay_song=lambda: (_ for _ in ()).throw(ValueError("yt-dlp failed")),
    )

    manager.after_playback(None)

    assert list(manager.queue) == []
    assert manager.idle is True


@pytest.mark.asyncio
async def test_next_skips_track_when_hydration_fails():
    song = make_song("Track A")
    manager = make_manager(song)
    manager.resolver = SimpleNamespace(
        hydrate=lambda song: (_ for _ in ()).throw(ValueError("bad metadata"))
    )

    await manager.next()

    assert list(manager.queue) == []
    assert manager.curr_song is None
    assert manager.idle is True


@pytest.mark.asyncio
async def test_opus_track_starts_without_ffmpeg_probe(monkeypatch):
    calls = []

    class FakeFFmpegOpusAudio:
        def __init__(self, source, **kwargs):
            calls.append(("direct", source, kwargs))

        @classmethod
        async def from_probe(cls, source, **kwargs):
            calls.append(("probe", source, kwargs))
            return cls(source, **kwargs)

    monkeypatch.setattr("bot.core.playback.FFmpegOpusAudio", FakeFFmpegOpusAudio)
    manager = make_manager()
    song = make_song("Track A")
    song.url = "https://example.test/audio.webm"
    song.audio_codec = "opus"

    await manager.create_audio_source(song, {"options": "-vn"})

    assert calls == [
        (
            "direct",
            "https://example.test/audio.webm",
            {"codec": "copy", "options": "-vn"},
        )
    ]


@pytest.mark.asyncio
async def test_non_opus_track_uses_ffmpeg_probe(monkeypatch):
    calls = []

    class FakeFFmpegOpusAudio:
        def __init__(self, source, **kwargs):
            calls.append(("direct", source, kwargs))

        @classmethod
        async def from_probe(cls, source, **kwargs):
            calls.append(("probe", source, kwargs))
            return cls(source, **kwargs)

    monkeypatch.setattr("bot.core.playback.FFmpegOpusAudio", FakeFFmpegOpusAudio)
    manager = make_manager()
    song = make_song("Track A")
    song.url = "https://example.test/audio.m4a"
    song.audio_codec = "mp4a.40.2"

    await manager.create_audio_source(song, {"options": "-vn"})

    assert calls[0] == (
        "probe",
        "https://example.test/audio.m4a",
        {"options": "-vn"},
    )


@pytest.mark.asyncio
async def test_prefetch_next_track_hydrates_second_song():
    first = make_song("Track A")
    second = make_song("Track B")
    manager = make_manager(first, second)
    manager.client = SimpleNamespace(loop=asyncio.get_running_loop())

    def hydrate(song):
        song.url = f"https://example.test/{song.title}.webm"
        song.audio_codec = "opus"
        return song

    manager.resolver = SimpleNamespace(hydrate=hydrate)

    manager.prefetch_next_track()
    await asyncio.gather(*list(manager._prefetch_tasks.values()))

    assert second.url == "https://example.test/Track B.webm"
    assert second.audio_codec == "opus"


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
