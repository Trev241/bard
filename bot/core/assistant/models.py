from dataclasses import dataclass
from enum import Enum


class AssistantAction(str, Enum):
    PLAY = "play"
    PAUSE = "pause"
    RESUME = "resume"
    SKIP = "skip"
    DISCONNECT = "disconnect"
    LOOP = "loop"
    LOOP_QUEUE = "loop_queue"
    NOW = "now"
    UNKNOWN = "unknown"


@dataclass
class AssistantIntent:
    action: AssistantAction
    query: str = ""
    confidence: float = 0.0
    raw_text: str = ""
    source: str = "rules"

    @property
    def understood(self):
        return self.action != AssistantAction.UNKNOWN


@dataclass
class AssistantResult:
    handled: bool
    message: str
    speak: bool = True
