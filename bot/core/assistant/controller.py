import logging

from bot.core.assistant.models import AssistantAction, AssistantIntent, AssistantResult
from bot.core.models import MusicRequest, Source

logger = logging.getLogger(__name__)


class AssistantController:
    def __init__(self, client):
        self.client = client

    async def execute(self, ctx, intent: AssistantIntent) -> AssistantResult:
        music = self.client.get_cog("Music")
        if not music:
            return AssistantResult(False, "Music controls are not available.")

        action = intent.action

        if action == AssistantAction.PLAY:
            return await self.play(music, ctx, intent)
        if action == AssistantAction.PAUSE:
            music.pause(ctx)
            return AssistantResult(True, "Paused.")
        if action == AssistantAction.RESUME:
            music.resume(ctx)
            return AssistantResult(True, "Resumed.")
        if action == AssistantAction.SKIP:
            music.skip(ctx)
            return AssistantResult(True, "Skipped.")
        if action == AssistantAction.DISCONNECT:
            await music.disconnect(ctx)
            return AssistantResult(True, "Disconnected.", speak=False)
        if action == AssistantAction.LOOP:
            music.loop()
            state = "Looping this track." if music.service.is_looping() else "Stopped looping this track."
            return AssistantResult(True, state)
        if action == AssistantAction.LOOP_QUEUE:
            looping = music.service.toggle_queue_loop()
            state = "Looping the queue." if looping else "Stopped looping the queue."
            return AssistantResult(True, state)
        if action == AssistantAction.NOW:
            await music.send_song_dtls(ctx=ctx)
            return AssistantResult(True, "I sent the current track.", speak=False)

        return AssistantResult(False, "I did not understand that.")

    async def play(self, music, ctx, intent: AssistantIntent) -> AssistantResult:
        query = intent.query.strip()
        if not query:
            return AssistantResult(False, "What would you like me to play?")

        if music.voice_state == music.VOICE_DISCONNECTED:
            await music.join(ctx)

        await music.play(MusicRequest(query, ctx.author, ctx, Source.VOICE))
        return AssistantResult(True, f"Searching for {query}.", speak=False)
