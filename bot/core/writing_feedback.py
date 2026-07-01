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

    @property
    def is_max_tokens(self) -> bool:
        return getattr(self, "finish_reason", None) == "MAX_TOKENS"


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
    rewrite_notes: Tuple[str, ...] = ()
    llm_rewrite: bool = False

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
    include_notes: bool = False


@dataclass(frozen=True)
class WritingRewriteResult:
    recommendation: str
    notes: Tuple[str, ...] = ()


class WritingFeedbackProvider(Protocol):
    name: str

    def supports(self, language: str) -> bool:
        ...

    def check_sync(self, request: WritingFeedbackRequest) -> WritingFeedbackResult:
        ...


class WritingRewriteProvider(Protocol):
    name: str

    def rewrite_sync(
        self, request: WritingRewriteRequest
    ) -> Optional[WritingRewriteResult]:
        ...


class WritingFeedbackService:
    def __init__(
        self,
        providers: Iterable[WritingFeedbackProvider],
        *,
        rewrite_provider: Optional[WritingRewriteProvider] = None,
        score_threshold: int = 75,
        recommend_threshold: int = 45,
        auto_rewrite_threshold: int = 25,
    ):
        self.providers = list(providers)
        self.rewrite_provider = rewrite_provider
        self.score_threshold = _clamp_score(score_threshold)
        self.recommend_threshold = _clamp_score(recommend_threshold)
        self.auto_rewrite_threshold = _clamp_score(auto_rewrite_threshold)

    async def check(
        self, request: WritingFeedbackRequest
    ) -> Optional[WritingFeedbackResult]:
        result = await self.assess(request)
        if result is None:
            return None

        if result.score > self.score_threshold:
            return None

        if result.score <= self.auto_rewrite_threshold:
            return await self.assess(request, force_rewrite=True)

        if result.score > self.recommend_threshold:
            return WritingFeedbackResult(
                score=result.score,
                language=result.language,
                source_text=result.source_text,
                provider=result.provider,
                issues=result.issues,
                recommendation=None,
                rewrite_notes=(),
                llm_rewrite=False,
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
        rewrite_notes = result.rewrite_notes
        llm_rewrite = result.llm_rewrite
        if force_rewrite:
            rewrite = await self._rewrite(
                result,
                normalized_request.context,
                include_notes=True,
            )
            if rewrite.recommendation:
                recommendation = rewrite.recommendation
                llm_rewrite = True
            rewrite_notes = rewrite.notes

        if (
            recommendation != result.recommendation
            or rewrite_notes != result.rewrite_notes
            or llm_rewrite != result.llm_rewrite
        ):
            return WritingFeedbackResult(
                score=result.score,
                language=result.language,
                source_text=result.source_text,
                provider=result.provider,
                issues=result.issues,
                recommendation=recommendation,
                rewrite_notes=rewrite_notes,
                llm_rewrite=llm_rewrite,
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
        self,
        result: WritingFeedbackResult,
        context: dict,
        *,
        include_notes: bool = False,
    ) -> WritingRewriteResult:
        if self.rewrite_provider is None:
            return WritingRewriteResult(result.recommendation or "", ())

        request = WritingRewriteRequest(
            text=result.source_text,
            language=result.language,
            score=result.score,
            issues=result.issues,
            conversation_context=tuple(context.get("conversation_context") or ()),
            include_notes=include_notes,
        )

        try:
            rewrite = await asyncio.to_thread(
                self.rewrite_provider.rewrite_sync,
                request,
            )
        except WritingRewriteUnavailable as exc:
            log.info("Writing rewrite skipped: %s", exc)
            return WritingRewriteResult(result.recommendation or "", ())
        except WritingRewriteInvalidResponse as exc:
            log.info("Writing rewrite returned unusable response: %s", exc)
            return WritingRewriteResult(result.recommendation or "", ())
        except requests.RequestException as exc:
            log.info("Writing rewrite request failed: %s", exc)
            return WritingRewriteResult(result.recommendation or "", ())
        except Exception:
            log.warning("Unexpected writing rewrite provider failure.", exc_info=True)
            return WritingRewriteResult(result.recommendation or "", ())

        if rewrite is None:
            return WritingRewriteResult(result.recommendation or "", ())

        recommendation = rewrite.recommendation.strip()
        if not recommendation or recommendation == result.source_text.strip():
            return WritingRewriteResult(result.recommendation or "", ())

        return WritingRewriteResult(
            recommendation=recommendation,
            notes=tuple(note.strip() for note in rewrite.notes if note.strip()),
        )


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
    REWRITE_MAX_OUTPUT_TOKENS = 256
    REWRITE_WITH_NOTES_MAX_OUTPUT_TOKENS = 1024
    REWRITE_WITH_NOTES_RETRY_MAX_OUTPUT_TOKENS = 1536
    DEFAULT_SYSTEM_PROMPT = (
        "You help French learners write natural, correct French. "
        "Return only JSON. "
        "The recommendation must be one complete French rewrite of the user's "
        "sentence. Preserve the original meaning, person, tense, tone, names, "
        "and Discord-style casualness. Do not translate to English."
    )
    name = "gemini"

    def __init__(
        self,
        api_key: str,
        model: str,
        *,
        timeout_seconds: float = 4.0,
        rate_limit_cooldown_seconds: float = 300.0,
        extra_instructions: str = "",
    ):
        self.api_key = api_key
        self.models = tuple(item.strip() for item in model.split(",") if item.strip())
        self.model = self.models[0] if self.models else ""
        self.timeout_seconds = timeout_seconds
        self.rate_limit_cooldown_seconds = max(0.0, rate_limit_cooldown_seconds)
        self.extra_instructions = extra_instructions.strip()
        self._cooldown_until = 0.0

    @property
    def available(self):
        return bool(self.api_key and self.models)

    def rewrite_sync(
        self, request: WritingRewriteRequest
    ) -> Optional[WritingRewriteResult]:
        if not self.available:
            return None
        if self._is_cooling_down():
            remaining = int(max(1, self._cooldown_until - time.monotonic()))
            raise WritingRewriteUnavailable(
                f"Gemini rate-limit cooldown active for {remaining}s"
            )

        rate_limited_models = []
        transient_failed_models = []
        last_error = None
        for model in self.models:
            try:
                return self._rewrite_with_model(request, model)
            except requests.Timeout as exc:
                transient_failed_models.append(model)
                last_error = exc
                continue
            except requests.HTTPError as exc:
                status_code = (
                    exc.response.status_code if exc.response is not None else None
                )
                if status_code == 429:
                    rate_limited_models.append(model)
                    last_error = exc
                    continue
                if status_code in {502, 503, 504}:
                    transient_failed_models.append(model)
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

        if transient_failed_models:
            raise WritingRewriteUnavailable(
                "Gemini rewrite models were temporarily unavailable: "
                f"{', '.join(transient_failed_models)}"
            ) from last_error

        return None

    def _rewrite_with_model(
        self, request: WritingRewriteRequest, model: str
    ) -> Optional[WritingRewriteResult]:
        max_output_tokens = self.max_output_tokens_for(request)
        try:
            return self._rewrite_with_model_once(
                request,
                model,
                max_output_tokens=max_output_tokens,
            )
        except WritingRewriteInvalidResponse as exc:
            if not request.include_notes or not exc.is_max_tokens:
                raise
            return self._rewrite_with_model_once(
                request,
                model,
                max_output_tokens=self.REWRITE_WITH_NOTES_RETRY_MAX_OUTPUT_TOKENS,
            )

    def _rewrite_with_model_once(
        self,
        request: WritingRewriteRequest,
        model: str,
        *,
        max_output_tokens: int,
    ) -> Optional[WritingRewriteResult]:
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
                    "maxOutputTokens": max_output_tokens,
                    "responseMimeType": "application/json",
                    "responseSchema": self.response_schema(request.include_notes),
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
            data = self.json_from_content(content)
        except json.JSONDecodeError as exc:
            snippet = " ".join(content.split())[:120]
            finish_reason = self.finish_reason_from_payload(payload)
            if finish_reason:
                snippet = f"{snippet} [finishReason={finish_reason}]"
            error = WritingRewriteInvalidResponse(
                f"Gemini returned non-JSON content: {snippet!r}"
            )
            error.finish_reason = finish_reason
            raise error from exc
        return self.rewrite_result_from_data(data, include_notes=request.include_notes)

    @classmethod
    def max_output_tokens_for(cls, request: WritingRewriteRequest) -> int:
        if request.include_notes:
            return cls.REWRITE_WITH_NOTES_MAX_OUTPUT_TOKENS
        return cls.REWRITE_MAX_OUTPUT_TOKENS

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

    def system_prompt(self):
        if not self.extra_instructions:
            return self.DEFAULT_SYSTEM_PROMPT
        return (
            f"{self.DEFAULT_SYSTEM_PROMPT}\n\n"
            f"Additional correction instructions:\n{self.extra_instructions}"
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
        note_instruction = (
            "Also include notes: 1 to 2 brief English bullet-style explanations. "
            "Each note must be at most 12 words. "
            "Focus primarily on the corrections and the reasoning behind each "
            "correction. Return exactly this JSON shape: "
            '{"recommendation":"...","notes":["..."]}.'
            if request.include_notes
            else 'Return exactly this JSON shape: {"recommendation":"..."}.'
        )
        return (
            f"Language: {request.language}\n"
            f"Score: {request.score}/100\n"
            f"{context_block}"
            f"Original sentence:\n{request.text}\n\n"
            f"Detected issues:\n{issues}\n\n"
            "Rewrite only the original sentence in natural, correct French. "
            "Use the context only to preserve meaning; do not answer the conversation. "
            f"{note_instruction}"
        )

    @staticmethod
    def recommendation_from_data(data: dict) -> Optional[str]:
        recommendation = str(data.get("recommendation") or "").strip()
        if not recommendation:
            return None
        return recommendation.strip("\"'")

    @classmethod
    def rewrite_result_from_data(
        cls, data: dict, *, include_notes: bool = False
    ) -> Optional[WritingRewriteResult]:
        recommendation = cls.recommendation_from_data(data)
        if not recommendation:
            return None

        notes = ()
        if include_notes:
            raw_notes = data.get("notes") or ()
            if isinstance(raw_notes, str):
                raw_notes = (raw_notes,)
            if not isinstance(raw_notes, (list, tuple)):
                raise WritingRewriteInvalidResponse(
                    "Gemini response included invalid rewrite notes"
                )
            notes = tuple(str(note).strip() for note in raw_notes if str(note).strip())

        return WritingRewriteResult(recommendation=recommendation, notes=notes)

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

    @staticmethod
    def finish_reason_from_payload(payload: dict) -> Optional[str]:
        try:
            finish_reason = payload["candidates"][0].get("finishReason")
        except (KeyError, IndexError, TypeError):
            return None
        return str(finish_reason) if finish_reason else None

    @staticmethod
    def json_from_content(content: str) -> dict:
        text = content.strip()
        if text.startswith("```"):
            lines = text.splitlines()
            if lines and lines[0].startswith("```"):
                lines = lines[1:]
            if lines and lines[-1].strip().startswith("```"):
                lines = lines[:-1]
            text = "\n".join(lines).strip()

        try:
            return json.loads(text)
        except json.JSONDecodeError:
            start = text.find("{")
            end = text.rfind("}")
            if start == -1 or end == -1 or end <= start:
                raise
            return json.loads(text[start : end + 1])

    @staticmethod
    def response_schema(include_notes: bool = False) -> dict:
        properties = {
            "recommendation": {
                "type": "STRING",
                "description": "One complete rewrite in the requested language.",
            },
        }
        required = ["recommendation"]

        if include_notes:
            properties["notes"] = {
                "type": "ARRAY",
                "description": (
                    "Short English explanations of the corrections and why each "
                    "correction is needed."
                ),
                "items": {"type": "STRING"},
            }
            required.append("notes")

        return {
            "type": "OBJECT",
            "properties": properties,
            "required": required,
        }

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
