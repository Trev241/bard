from types import SimpleNamespace

import pytest

from bot.core.assistant.controller import AssistantController
from bot.core.assistant.models import AssistantAction, AssistantIntent
from bot.core.models import Source


class FakeClient:
    def __init__(self, music):
        self.music = music

    def get_cog(self, name):
        if name == "Music":
            return self.music
        return None


class FakeService:
    def __init__(self):
        self.looping = False
        self.looping_queue = False

    def is_looping(self):
        return self.looping

    def toggle_queue_loop(self):
        self.looping_queue = not self.looping_queue
        return self.looping_queue


class FakeMusic:
    VOICE_DISCONNECTED = "DISCONNECTED"
    VOICE_CONNECTED = "CONNECTED"

    def __init__(self):
        self.voice_state = self.VOICE_CONNECTED
        self.service = FakeService()
        self.requests = []
        self.paused = False
        self.resumed = False
        self.skipped = False
        self.disconnected = False
        self.joined = False

    async def join(self, ctx):
        self.joined = True
        self.voice_state = self.VOICE_CONNECTED

    async def play(self, request):
        self.requests.append(request)

    def pause(self, ctx):
        self.paused = True

    def resume(self, ctx):
        self.resumed = True

    def skip(self, ctx):
        self.skipped = True

    async def disconnect(self, ctx):
        self.disconnected = True

    def loop(self):
        self.service.looping = not self.service.looping

    async def send_song_dtls(self, ctx):
        self.sent_now = True


def make_ctx():
    return SimpleNamespace(author=SimpleNamespace(display_name="tester"))


@pytest.mark.asyncio
async def test_controller_dispatches_voice_play_request():
    music = FakeMusic()
    controller = AssistantController(FakeClient(music))

    result = await controller.execute(
        make_ctx(),
        AssistantIntent(AssistantAction.PLAY, query="daft punk", confidence=1.0),
    )

    assert result.handled is True
    assert result.speak is False
    assert len(music.requests) == 1
    assert music.requests[0].query == "daft punk"
    assert music.requests[0].source == Source.VOICE


@pytest.mark.asyncio
async def test_controller_joins_before_playing_if_disconnected():
    music = FakeMusic()
    music.voice_state = music.VOICE_DISCONNECTED
    controller = AssistantController(FakeClient(music))

    await controller.execute(
        make_ctx(),
        AssistantIntent(AssistantAction.PLAY, query="lofi", confidence=1.0),
    )

    assert music.joined is True
    assert music.requests[0].query == "lofi"


@pytest.mark.asyncio
async def test_controller_dispatches_playback_controls():
    music = FakeMusic()
    controller = AssistantController(FakeClient(music))
    ctx = make_ctx()

    await controller.execute(ctx, AssistantIntent(AssistantAction.PAUSE, confidence=1.0))
    await controller.execute(ctx, AssistantIntent(AssistantAction.RESUME, confidence=1.0))
    await controller.execute(ctx, AssistantIntent(AssistantAction.SKIP, confidence=1.0))

    assert music.paused is True
    assert music.resumed is True
    assert music.skipped is True


@pytest.mark.asyncio
async def test_controller_dispatches_disconnect_without_spoken_reply():
    music = FakeMusic()
    controller = AssistantController(FakeClient(music))

    result = await controller.execute(
        make_ctx(),
        AssistantIntent(AssistantAction.DISCONNECT, confidence=1.0),
    )

    assert music.disconnected is True
    assert result.speak is False
