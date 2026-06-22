from types import SimpleNamespace

import pytest

from bot.core.exceptions import ConnectionNotReady
from bot.core.models import MusicRequest, Song
from bot.core.music_service import MusicService, QueueOutcome


class FakePlayback:
    def __init__(self, songs):
        self.songs = songs
        self.play_count = 0
        self.looping = False
        self.looping_queue = False
        self.queue = list(songs or [])
        self.playback_enabled = SimpleNamespace(is_set=lambda: True)

    def search_and_add(self, request):
        return self.songs

    async def play(self):
        self.play_count += 1

    def loop(self):
        self.looping = not self.looping

    def loop_queue(self):
        self.looping_queue = not self.looping_queue


def make_song(title):
    return Song(
        title=title,
        duration="0:01:00",
        requester=SimpleNamespace(display_name="tester"),
        ie_result={},
    )


@pytest.mark.asyncio
async def test_service_requires_playback():
    service = MusicService(SimpleNamespace())

    with pytest.raises(ConnectionNotReady):
        await service.request_tracks(MusicRequest("query", SimpleNamespace()))


@pytest.mark.asyncio
async def test_service_returns_no_results_without_starting_playback():
    playback = FakePlayback([])
    service = MusicService(SimpleNamespace(), playback)

    result = await service.request_tracks(MusicRequest("query", SimpleNamespace()))

    assert result.outcome == QueueOutcome.NO_RESULTS
    assert playback.play_count == 0


@pytest.mark.asyncio
async def test_service_returns_queued_and_starts_playback():
    song = make_song("Track A")
    playback = FakePlayback([song])
    service = MusicService(SimpleNamespace(), playback)

    result = await service.request_tracks(MusicRequest("query", SimpleNamespace()))

    assert result.outcome == QueueOutcome.QUEUED
    assert result.songs == [song]
    assert playback.play_count == 1


@pytest.mark.asyncio
async def test_service_returns_random_for_empty_query():
    playback = FakePlayback(None)
    service = MusicService(SimpleNamespace(), playback)

    result = await service.request_tracks(MusicRequest(None, SimpleNamespace()))

    assert result.outcome == QueueOutcome.RANDOM
    assert playback.play_count == 1


def test_service_toggles_loop_state():
    playback = FakePlayback([make_song("Track A")])
    service = MusicService(SimpleNamespace(), playback)

    assert service.toggle_loop() is True
    assert service.toggle_loop() is False

