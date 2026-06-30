import asyncio
import json
import logging
import time
from dataclasses import dataclass, field
from typing import Iterable, Optional, Protocol, Tuple

import requests


log = logging.getLogger(__name__)


class WritingFeedbackError(Exception):
    """Raised when a writing feedback request cannot be completed."""


class WritingRewriteUnavailable(Exception):
    """Raised when optional LLM rewriting is temporarily unavailable."""


class WritingRewriteInvalidResponse(Exception):
    """Raised when an LLM rewrite response cannot be used."""


@dataclass(frozen=True)
class WritingFeedbackIssue:
    start: int
    end: int
    message: str
    issue_type: str = "grammar"
    suggestions: Tuple[str, ...] = ()


@dataclass(frozen=True)
class WritingFeedbackRequest:
    text: str
    language: str
    context: dict = field(default_factory=dict)


@dataclass(frozen=True)
class WritingFeedbackResult:
    score: int
    language: str
    source_text: str
    provider: str
    issues: Tuple[WritingFeedbackIssue, ...] = ()
    recommendation: Optional[str] = None

    @property
    def needs_feedback(self) -> bool:
        return bool(self.issues)


@dataclass(frozen=True)
class WritingRewriteRequest:
    text: str
    language: str
    score: int
    issues: Tuple[WritingFeedbackIssue, ...] = ()
    conversation_context: Tuple[str, ...] = ()


class WritingFeedbackProvider(Protocol):
    name: str

    def supports(self, language: str) -> bool:
        ...

    def check_sync(self, request: WritingFeedbackRequest) -> WritingFeedbackResult:
        ...


class WritingRewriteProvider(Protocol):
    name: str

    def rewrite_sync(self, request: WritingRewriteRequest) -> Optional[str]:
        ...


class WritingFeedbackService:
    def __init__(
        self,
        providers: Iterable[WritingFeedbackProvider],
        *,
        rewrite_provider: Optional[WritingRewriteProvider] = None,
        score_threshold: int = 75,
        recommend_threshold: int = 45,
    ):
        self.providers = list(providers)
        self.rewrite_provider = rewrite_provider
        self.score_threshold = _clamp_score(score_threshold)
        self.recommend_threshold = _clamp_score(recommend_threshold)

    async def check(
        self, request: WritingFeedbackRequest
    ) -> Optional[WritingFeedbackResult]:
        result = await self.assess(request)
        if result is None:
            return None

        if result.score > self.score_threshold:
            return None

        if result.score > self.recommend_threshold:
            return WritingFeedbackResult(
                score=result.score,
                language=result.language,
                source_text=result.source_text,
                provider=result.provider,
                issues=result.issues,
                recommendation=None,
            )

        return result

    async def assess(
        self,
        request: WritingFeedbackRequest,
        *,
        force_rewrite: bool = False,
    ) -> Optional[WritingFeedbackResult]:
        text = request.text.strip()
        if not text:
            return None

        normalized_request = WritingFeedbackRequest(
            text=text,
            language=request.language.strip().casefold(),
            context=request.context or {},
        )
        provider = self._select_provider(normalized_request.language)
        result = await asyncio.to_thread(provider.check_sync, normalized_request)

        recommendation = result.recommendation
        if force_rewrite or result.score <= self.recommend_threshold:
            recommendation = await self._rewrite(result, normalized_request.context)

        if recommendation != result.recommendation:
            return WritingFeedbackResult(
                score=result.score,
                language=result.language,
                source_text=result.source_text,
                provider=result.provider,
                issues=result.issues,
                recommendation=recommendation,
            )

        return result

    def _select_provider(self, language: str) -> WritingFeedbackProvider:
        for provider in self.providers:
            if provider.supports(language):
                return provider

        raise WritingFeedbackError(
            f"No writing feedback provider supports {language!r}."
        )

    async def _rewrite(
        self, result: WritingFeedbackResult, context: dict
    ) -> Optional[str]:
        if self.rewrite_provider is None:
            return result.recommendation

        request = WritingRewriteRequest(
            text=result.source_text,
            language=result.language,
            score=result.score,
            issues=result.issues,
            conversation_context=tuple(context.get("conversation_context") or ()),
        )

        try:
            recommendation = await asyncio.to_thread(
                self.rewrite_provider.rewrite_sync,
                request,
            )
        except WritingRewriteUnavailable as exc:
            log.info("Writing rewrite skipped: %s", exc)
            return result.recommendation
        except WritingRewriteInvalidResponse as exc:
            log.info("Writing rewrite returned unusable response: %s", exc)
            return result.recommendation
        except requests.RequestException as exc:
            log.info("Writing rewrite request failed: %s", exc)
            return result.recommendation
        except Exception:
            log.warning("Unexpected writing rewrite provider failure.", exc_info=True)
            return result.recommendation

        if recommendation and recommendation.strip() != result.source_text.strip():
            return recommendation.strip()
        return result.recommendation


class GrammalecteWritingFeedbackProvider:
    name = "grammalecte"

    def __init__(self, languages: Iterable[str] = ("fr",)):
        self.languages = {language.casefold() for language in languages}
        self._engine = None

    def supports(self, language: str) -> bool:
        return language.casefold() in self.languages

    def check_sync(
        self, request: WritingFeedbackRequest
    ) -> WritingFeedbackResult:
        engine = self._load_engine()
        raw_errors = engine.parse(request.text, "FR", False)
        issues = tuple(self._issue_from_error(error) for error in raw_errors)
        score = score_issues(request.text, issues)
        recommendation = build_recommendation(request.text, issues)

        return WritingFeedbackResult(
            score=score,
            language=request.language,
            source_text=request.text,
            provider=self.name,
            issues=issues,
            recommendation=recommendation,
        )

    def _load_engine(self):
        if self._engine is not None:
            return self._engine

        try:
            from grammalecte.fr import gc_engine
        except ImportError as exc:
            raise WritingFeedbackError(
                "Grammalecte is not installed. Install grammalecte or disable "
                "WRITING_FEEDBACK_ENABLED."
            ) from exc

        gc_engine.load()
        self._engine = gc_engine
        return self._engine

    @staticmethod
    def _issue_from_error(error) -> WritingFeedbackIssue:
        suggestions = error.get("aSuggestions") or ()
        return WritingFeedbackIssue(
            start=int(error.get("nStart", 0)),
            end=int(error.get("nEnd", 0)),
            message=str(error.get("sMessage", "Writing issue detected.")),
            issue_type=str(error.get("sType", "grammar")),
            suggestions=tuple(str(item) for item in suggestions if str(item).strip()),
        )


class GeminiWritingRewriteProvider:
    BASE_URL = "https://generativelanguage.googleapis.com/v1beta"
    name = "gemini"

    def __init__(
        self,
        api_key: str,
        model: str,
        *,
        timeout_seconds: float = 4.0,
        rate_limit_cooldown_seconds: float = 300.0,
    ):
        self.api_key = api_key
        self.models = tuple(item.strip() for item in model.split(",") if item.strip())
        self.model = self.models[0] if self.models else ""
        self.timeout_seconds = timeout_seconds
        self.rate_limit_cooldown_seconds = max(0.0, rate_limit_cooldown_seconds)
        self._cooldown_until = 0.0

    @property
    def available(self):
        return bool(self.api_key and self.models)

    def rewrite_sync(self, request: WritingRewriteRequest) -> Optional[str]:
        if not self.available:
            return None
        if self._is_cooling_down():
            remaining = int(max(1, self._cooldown_until - time.monotonic()))
            raise WritingRewriteUnavailable(
                f"Gemini rate-limit cooldown active for {remaining}s"
            )

        rate_limited_models = []
        last_error = None
        for model in self.models:
            try:
                return self._rewrite_with_model(request, model)
            except requests.HTTPError as exc:
                if exc.response is not None and exc.response.status_code == 429:
                    rate_limited_models.append(model)
                    last_error = exc
                    continue
                raise

        if rate_limited_models:
            self._start_rate_limit_cooldown(
                last_error.response if last_error is not None else None
            )
            raise WritingRewriteUnavailable(
                "Gemini returned 429 Too Many Requests for all configured "
                f"rewrite models: {', '.join(rate_limited_models)}"
            ) from last_error

        return None

    def _rewrite_with_model(
        self, request: WritingRewriteRequest, model: str
    ) -> Optional[str]:
        response = requests.post(
            self.endpoint_for_model(model),
            headers={
                "x-goog-api-key": self.api_key,
                "Content-Type": "application/json",
            },
            json={
                "system_instruction": {
                    "parts": [{"text": self.system_prompt()}],
                },
                "contents": [
                    {
                        "role": "user",
                        "parts": [{"text": self.user_prompt(request)}],
                    },
                ],
                "generationConfig": {
                    "temperature": 0.2,
                    "maxOutputTokens": 180,
                    "responseMimeType": "application/json",
                    "responseSchema": {
                        "type": "OBJECT",
                        "properties": {
                            "recommendation": {
                                "type": "STRING",
                                "description": (
                                    "One complete rewrite in the requested language."
                                ),
                            },
                        },
                        "required": ["recommendation"],
                    },
                },
            },
            timeout=self.timeout_seconds,
        )
        try:
            response.raise_for_status()
        except requests.HTTPError as exc:
            raise

        payload = response.json()
        content = self.content_from_payload(payload)
        try:
            data = json.loads(content)
        except json.JSONDecodeError as exc:
            raise WritingRewriteInvalidResponse("Gemini returned non-JSON content") from exc
        return self.recommendation_from_data(data)

    def _is_cooling_down(self) -> bool:
        return time.monotonic() < self._cooldown_until

    def _start_rate_limit_cooldown(self, response) -> None:
        retry_after = response.headers.get("Retry-After") if response else None
        try:
            cooldown_seconds = float(retry_after) if retry_after else None
        except ValueError:
            cooldown_seconds = None

        if cooldown_seconds is None:
            cooldown_seconds = self.rate_limit_cooldown_seconds

        self._cooldown_until = time.monotonic() + max(0.0, cooldown_seconds)

    @staticmethod
    def system_prompt():
        return (
            "You help French learners write natural, correct French. "
            "Return only JSON with key recommendation. "
            "The recommendation must be one complete French rewrite of the user's "
            "sentence. Preserve the original meaning, person, tense, tone, names, "
            "and Discord-style casualness. Do not translate to English. Do not add "
            "explanations."
        )

    @staticmethod
    def user_prompt(request: WritingRewriteRequest):
        issue_lines = []
        for issue in request.issues:
            suggestions = ", ".join(issue.suggestions)
            suffix = f" Suggestions: {suggestions}" if suggestions else ""
            issue_lines.append(f"- {issue.message}{suffix}")

        issues = "\n".join(issue_lines) if issue_lines else "- No structured issues."
        context = "\n".join(
            f"- {item}" for item in request.conversation_context if item.strip()
        )
        context_block = (
            f"Conversation context:\n{context}\n\n"
            if context
            else "Conversation context:\n- None\n\n"
        )
        return (
            f"Language: {request.language}\n"
            f"Score: {request.score}/100\n"
            f"{context_block}"
            f"Original sentence:\n{request.text}\n\n"
            f"Detected issues:\n{issues}\n\n"
            "Rewrite only the original sentence in natural, correct French. "
            "Use the context only to preserve meaning; do not answer the conversation."
        )

    @staticmethod
    def recommendation_from_data(data: dict) -> Optional[str]:
        recommendation = str(data.get("recommendation") or "").strip()
        if not recommendation:
            return None
        return recommendation.strip("\"'")

    @staticmethod
    def content_from_payload(payload: dict) -> str:
        try:
            parts = payload["candidates"][0]["content"]["parts"]
            text_parts = [
                part.get("text", "")
                for part in parts
                if isinstance(part, dict) and part.get("text")
            ]
            content = "".join(text_parts)
        except (KeyError, IndexError, TypeError) as exc:
            raise WritingRewriteInvalidResponse(
                "Gemini response did not include candidate text"
            ) from exc

        if not isinstance(content, str) or not content.strip():
            raise WritingRewriteInvalidResponse(
                "Gemini response included empty candidate text"
            )

        return content

    @classmethod
    def endpoint_for_model(cls, model: str) -> str:
        model_path = model if model.startswith("models/") else f"models/{model}"
        return f"{cls.BASE_URL}/{model_path}:generateContent"


def score_issues(text: str, issues: Iterable[WritingFeedbackIssue]) -> int:
    issue_list = list(issues)
    if not issue_list:
        return 100

    word_count = max(1, len(text.split()))
    penalty = 0
    for issue in issue_list:
        issue_type = issue.issue_type.casefold()
        if "orth" in issue_type or "spell" in issue_type:
            penalty += 8
        elif "typo" in issue_type or "nbsp" in issue_type:
            penalty += 3
        else:
            penalty += 12

    density_penalty = max(0, len(issue_list) - 1) * 3
    short_text_penalty = 8 if word_count <= 4 and issue_list else 0

    return _clamp_score(100 - penalty - density_penalty - short_text_penalty)


def build_recommendation(
    text: str, issues: Iterable[WritingFeedbackIssue]
) -> Optional[str]:
    replacements = []
    for issue in issues:
        if not issue.suggestions:
            continue
        if issue.start < 0 or issue.end <= issue.start or issue.end > len(text):
            continue
        replacements.append((issue.start, issue.end, issue.suggestions[0]))

    if not replacements:
        return None

    recommendation = text
    for start, end, replacement in sorted(replacements, reverse=True):
        recommendation = recommendation[:start] + replacement + recommendation[end:]

    if recommendation == text:
        return None
    return recommendation


def _clamp_score(value: int) -> int:
    return max(0, min(100, int(value)))
