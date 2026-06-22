from types import SimpleNamespace

import pytest

from bot import config
from bot.core.models import MusicRequest
from bot.core.resolver import TrackResolver


class FakeYt:
    def sanitize_info(self, info):
        return info

    def process_ie_result(self, ie_result, download=False):
        return {
            "title": "Hydrated Track",
            "webpage_url": "https://example.test/watch",
            "format_id": "251",
            "thumbnails": [{"url": "https://example.test/thumb.jpg"}],
            "formats": [
                {"format_id": "140", "url": "https://example.test/audio-low.m4a"},
                {"format_id": "251", "url": "https://example.test/audio.webm"},
            ],
        }


def test_resolver_builds_song_from_entry():
    requester = SimpleNamespace(display_name="tester")
    resolver = TrackResolver(SimpleNamespace(user=SimpleNamespace()), yt=FakeYt())
    request = MusicRequest("query", requester)

    song = resolver.song_from_entry(
        {
            "title": "Track A",
            "duration": 125,
            "thumbnails": [{"url": "https://example.test/thumb.jpg"}],
        },
        request,
    )

    assert song.title == "Track A"
    assert song.duration == "0:02:05"
    assert song.requester == requester
    assert song.thumbnail == "https://example.test/thumb.jpg"


def test_resolver_hydrates_playable_metadata(monkeypatch, tmp_path):
    monkeypatch.setattr(config, "YTDLP_DUMP", tmp_path / "yt-dlp.json")
    requester = SimpleNamespace(display_name="tester")
    resolver = TrackResolver(SimpleNamespace(user=SimpleNamespace()), yt=FakeYt())
    song = resolver.song_from_entry({"title": "Track A", "duration": 1}, MusicRequest("query", requester))

    resolver.hydrate(song)

    assert song.webpage == "https://example.test/watch"
    assert song.url == "https://example.test/audio.webm"
    assert song.thumbnail == "https://example.test/thumb.jpg"


def test_resolver_rejects_missing_playable_format(monkeypatch, tmp_path):
    class NoFormatYt(FakeYt):
        def process_ie_result(self, ie_result, download=False):
            info = super().process_ie_result(ie_result, download)
            info["formats"] = []
            return info

    monkeypatch.setattr(config, "YTDLP_DUMP", tmp_path / "yt-dlp.json")
    requester = SimpleNamespace(display_name="tester")
    resolver = TrackResolver(SimpleNamespace(user=SimpleNamespace()), yt=NoFormatYt())
    song = resolver.song_from_entry({"title": "Track A", "duration": 1}, MusicRequest("query", requester))

    with pytest.raises(ValueError):
        resolver.hydrate(song)
