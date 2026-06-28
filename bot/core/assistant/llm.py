import asyncio
import json
import logging

import requests

from bot.core.assistant.models import AssistantAction, AssistantIntent

logger = logging.getLogger(__name__)


class IntentParserChain:
    def __init__(self, parsers, min_confidence=0.75):
        self.parsers = [parser for parser in parsers if parser is not None]
        self.min_confidence = min_confidence

    async def parse(self, text: str) -> AssistantIntent:
        fallback = AssistantIntent(
            action=AssistantAction.UNKNOWN,
            raw_text=text or "",
            confidence=0.0,
            source="none",
        )

        for parser in self.parsers:
            try:
                intent = await maybe_await(parser.parse(text))
            except Exception:
                logger.warning(
                    "Assistant intent parser %s failed.",
                    parser.__class__.__name__,
                    exc_info=True,
                )
                continue

            if intent.understood and intent.confidence >= self.min_confidence:
                return intent

            fallback = intent

        return fallback


async def maybe_await(value):
    if asyncio.iscoroutine(value):
        return await value
    return value


class OpenRouterIntentParser:
    ENDPOINT = "https://openrouter.ai/api/v1/chat/completions"

    def __init__(
        self,
        api_key: str,
        model: str,
        timeout_seconds: float = 2.0,
        app_name: str = "Bard Discord Bot",
    ):
        self.api_key = api_key
        self.model = model
        self.timeout_seconds = timeout_seconds
        self.app_name = app_name

    @property
    def available(self):
        return bool(self.api_key and self.model)

    async def parse(self, text: str) -> AssistantIntent:
        if not self.available:
            return self.unknown(text)

        return await asyncio.to_thread(self._parse_sync, text or "")

    def _parse_sync(self, text: str) -> AssistantIntent:
        response = requests.post(
            self.ENDPOINT,
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
                "X-Title": self.app_name,
            },
            json={
                "model": self.model,
                "messages": [
                    {
                        "role": "system",
                        "content": self.system_prompt(),
                    },
                    {
                        "role": "user",
                        "content": text,
                    },
                ],
                "temperature": 0,
                "max_tokens": 120,
                "response_format": {"type": "json_object"},
            },
            timeout=self.timeout_seconds,
        )
        response.raise_for_status()
        payload = response.json()
        content = payload["choices"][0]["message"]["content"]
        data = json.loads(content)
        return self.intent_from_data(text, data)

    @staticmethod
    def system_prompt():
        actions = ", ".join(action.value for action in AssistantAction)
        return (
            "You parse short voice commands for a Discord music bot named Bard. "
            "Return only JSON with keys: action, query, confidence. "
            f"Allowed actions: {actions}. "
            "Use action=play only when the user asks for music to be played or queued; "
            "put the requested song, artist, album, genre, or search phrase in query. "
            "Use unknown when the command is not clearly about controlling music playback. "
            "Do not invent a query. Confidence must be a number from 0 to 1."
        )

    @staticmethod
    def intent_from_data(raw_text: str, data: dict) -> AssistantIntent:
        action_value = str(data.get("action", "unknown")).strip().lower()
        try:
            action = AssistantAction(action_value)
        except ValueError:
            action = AssistantAction.UNKNOWN

        query = str(data.get("query") or "").strip()
        try:
            confidence = float(data.get("confidence", 0.0))
        except (TypeError, ValueError):
            confidence = 0.0

        confidence = max(0.0, min(confidence, 1.0))
        if action == AssistantAction.PLAY and not query:
            action = AssistantAction.UNKNOWN
            confidence = 0.0

        return AssistantIntent(
            action=action,
            query=query,
            confidence=confidence,
            raw_text=raw_text,
            source="openrouter",
        )

    @staticmethod
    def unknown(raw_text: str) -> AssistantIntent:
        return AssistantIntent(
            action=AssistantAction.UNKNOWN,
            confidence=0.0,
            raw_text=raw_text,
            source="openrouter",
        )
