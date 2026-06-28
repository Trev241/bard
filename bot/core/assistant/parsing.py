import re
import string

from bot.core.assistant.models import AssistantAction, AssistantIntent


class RuleBasedIntentParser:
    """
    Fast, local parser for Bard's small voice-control command surface.

    The parser intentionally returns UNKNOWN rather than guessing when an utterance
    is vague. Optional LLM parsers can handle those lower-confidence cases.
    """

    WAKE_PREFIX = re.compile(
        r"^\s*(?:(?:ok(?:ay)?|hey|hi|yo)\s+)?bard[\s,.:;-]*",
        re.IGNORECASE,
    )
    TRAILING_POLITENESS = re.compile(
        r"\s*(?:please|for me|thanks|thank you)[\s.?!]*$",
        re.IGNORECASE,
    )

    PLAY_PATTERNS = [
        re.compile(
            r"^(?:please\s+)?(?:can|could|would)\s+(?:you|we)\s+"
            r"(?:play|put on|queue|start playing|listen to|hear)\s+(?P<query>.+)$",
            re.IGNORECASE,
        ),
        re.compile(
            r"^(?:please\s+)?(?:i\s+want\s+(?:you\s+)?to|i(?:'d| would)\s+like\s+(?:you\s+)?to)\s+"
            r"(?:play|put on|queue|listen to|hear)\s+(?P<query>.+)$",
            re.IGNORECASE,
        ),
        re.compile(
            r"^(?:please\s+)?(?:play|put on|queue|start playing)\s+(?P<query>.+)$",
            re.IGNORECASE,
        ),
        re.compile(
            r"^(?:please\s+)?(?:let(?:'s| us)\s+)?(?:listen to|hear)\s+(?P<query>.+)$",
            re.IGNORECASE,
        ),
    ]

    def parse(self, text: str) -> AssistantIntent:
        raw_text = text or ""
        normalized = self.normalize(raw_text)
        if not normalized:
            return self.unknown(raw_text)

        play_intent = self.parse_play(normalized, raw_text)
        if play_intent.understood:
            return play_intent

        command_text = self.remove_filler(normalized)

        if self.matches_any(
            command_text,
            r"\b(disconnect|leave|leave\s+voice|leave\s+the\s+voice|quit|go\s+away)\b",
            r"\b(?:bye|goodbye)\s+bard\b",
        ):
            return self.intent(AssistantAction.DISCONNECT, raw_text, 0.96)

        if self.matches_any(
            command_text,
            r"\b(skip|next\s+(?:song|track)|go\s+next)\b",
            r"\bstop\s+(?:this|the)\s+(?:song|track)\b",
        ):
            return self.intent(AssistantAction.SKIP, raw_text, 0.96)

        if self.matches_any(
            command_text,
            r"\b(pause|hold\s+on|hold\s+up)\b",
            r"\bstop\s+(?:playing|the\s+music)\b",
        ):
            return self.intent(AssistantAction.PAUSE, raw_text, 0.94)

        if self.matches_any(
            command_text,
            r"\b(resume|unpause|continue|keep\s+playing|start\s+again)\b",
        ):
            return self.intent(AssistantAction.RESUME, raw_text, 0.94)

        if self.matches_any(
            command_text,
            r"\b(loop|repeat)\s+(?:the\s+)?(?:queue|playlist)\b",
        ):
            return self.intent(AssistantAction.LOOP_QUEUE, raw_text, 0.95)

        if self.matches_any(
            command_text,
            r"\b(loop|repeat)\s+(?:this|the)?\s*(?:song|track|music)?\b",
        ):
            return self.intent(AssistantAction.LOOP, raw_text, 0.9)

        if self.matches_any(
            command_text,
            r"\b(what(?:'s| is)\s+playing|what\s+song|name\s+(?:this|the)\s+song|now\s+playing)\b",
        ):
            return self.intent(AssistantAction.NOW, raw_text, 0.94)

        return self.unknown(raw_text)

    def parse_play(self, normalized: str, raw_text: str) -> AssistantIntent:
        for pattern in self.PLAY_PATTERNS:
            match = pattern.match(normalized)
            if not match:
                continue

            query = self.clean_query(match.group("query"))
            if not query:
                return self.unknown(raw_text)

            return self.intent(AssistantAction.PLAY, raw_text, 0.95, query=query)

        return self.unknown(raw_text)

    @classmethod
    def normalize(cls, text: str) -> str:
        normalized = text.strip()
        normalized = cls.WAKE_PREFIX.sub("", normalized)
        normalized = normalized.strip().strip(string.punctuation).strip()
        normalized = re.sub(r"\s+", " ", normalized)
        return normalized

    @classmethod
    def remove_filler(cls, text: str) -> str:
        text = re.sub(
            r"^(?:please\s+)?(?:(?:can|could|would)\s+(?:you|we)\s+)?",
            "",
            text,
            flags=re.IGNORECASE,
        )
        return text.strip()

    @classmethod
    def clean_query(cls, query: str) -> str:
        query = query.strip().strip("\"'")
        query = cls.TRAILING_POLITENESS.sub("", query)
        return query.strip().strip(string.punctuation).strip()

    @staticmethod
    def matches_any(text: str, *patterns: str) -> bool:
        return any(re.search(pattern, text, re.IGNORECASE) for pattern in patterns)

    @staticmethod
    def intent(
        action: AssistantAction,
        raw_text: str,
        confidence: float,
        query: str = "",
    ) -> AssistantIntent:
        return AssistantIntent(
            action=action,
            query=query,
            confidence=confidence,
            raw_text=raw_text,
            source="rules",
        )

    @staticmethod
    def unknown(raw_text: str) -> AssistantIntent:
        return AssistantIntent(
            action=AssistantAction.UNKNOWN,
            confidence=0.0,
            raw_text=raw_text,
            source="rules",
        )
