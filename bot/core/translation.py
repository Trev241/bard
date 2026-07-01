import asyncio
import json
import logging
import re
from collections import OrderedDict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable, Optional, Protocol, Tuple

import requests


log = logging.getLogger(__name__)
DEFAULT_NORMALIZATION_RULES_PATH = (
    Path(__file__).resolve().parents[1]
    / "resources"
    / "translation"
    / "normalization.en.json"
)


class TranslationError(Exception):
    """Raised when a translation request cannot be completed."""


@dataclass(frozen=True)
class LanguagePair:
    source: str
    target: str

    def reversed(self) -> "LanguagePair":
        return LanguagePair(source=self.target, target=self.source)


@dataclass(frozen=True)
class TranslationRequest:
    text: str
    pair: LanguagePair
    context: dict = field(default_factory=dict)


@dataclass(frozen=True)
class TranslationResult:
    translated_text: str
    provider: str
    source_text: str
    pair: LanguagePair
    alternatives: Tuple[str, ...] = ()
    notes: Tuple[str, ...] = ()


class TranslationProvider(Protocol):
    name: str

    def supports(self, pair: LanguagePair) -> bool:
        ...

    def warmup_sync(self) -> None:
        ...

    def translate_sync(self, request: TranslationRequest) -> TranslationResult:
        ...


class TranslationCache:
    def __init__(self, max_size: int = 1000):
        self.max_size = max(0, max_size)
        self._items: "OrderedDict[Tuple[str, str, str], TranslationResult]" = OrderedDict()

    def get(self, request: TranslationRequest) -> Optional[TranslationResult]:
        if self.max_size == 0:
            return None

        key = self._key(request)
        result = self._items.get(key)
        if result is None:
            return None

        self._items.move_to_end(key)
        return result

    def set(self, request: TranslationRequest, result: TranslationResult) -> None:
        if self.max_size == 0:
            return

        key = self._key(request)
        self._items[key] = result
        self._items.move_to_end(key)

        while len(self._items) > self.max_size:
            self._items.popitem(last=False)

    @staticmethod
    def _key(request: TranslationRequest) -> Tuple[str, str, str]:
        return (
            request.pair.source.casefold(),
            request.pair.target.casefold(),
            " ".join(request.text.split()),
        )


class TranslationService:
    def __init__(
        self,
        providers: Iterable[TranslationProvider],
        *,
        cache: Optional[TranslationCache] = None,
        max_concurrency: int = 1,
    ):
        self.providers = list(providers)
        self.cache = cache or TranslationCache()
        self.semaphore = asyncio.Semaphore(max(1, max_concurrency))

    async def warmup(self) -> None:
        for provider in self.providers:
            warmup_sync = getattr(provider, "warmup_sync", None)
            if warmup_sync is None:
                continue
            await asyncio.to_thread(warmup_sync)

    async def translate(self, request: TranslationRequest) -> TranslationResult:
        text = request.text.strip()
        if not text:
            raise TranslationError("Cannot translate an empty message.")

        normalized_request = TranslationRequest(
            text=text,
            pair=request.pair,
            context=request.context,
        )
        cached = self.cache.get(normalized_request)
        if cached is not None:
            return cached

        provider = self._select_provider(normalized_request.pair)
        async with self.semaphore:
            result = await asyncio.to_thread(provider.translate_sync, normalized_request)

        self.cache.set(normalized_request, result)
        return result

    def _select_provider(self, pair: LanguagePair) -> TranslationProvider:
        for provider in self.providers:
            if provider.supports(pair):
                return provider

        raise TranslationError(
            f"No translation provider supports {pair.source!r} -> {pair.target!r}."
        )


@dataclass(frozen=True)
class TextNormalization:
    text: str
    notes: Tuple[str, ...] = ()


class CasualEnglishNormalizer:
    source_languages = {"en", "eng", "english"}

    _FALLBACK_RULES = (
        {
            "pattern": r"\ban\s+llm\b",
            "replacement": "a large language model",
        },
        {
            "pattern": r"\bllm\b",
            "replacement": "large language model",
        },
        {
            "pattern": r"\bdon['\u2019]?t\b",
            "replacement": "do not",
        },
        {
            "pattern": r"\bbs\b",
            "replacement": "bullshit",
        },
        {
            "pattern": (
                r"\bur\s+(?=(?:using|doing|going|making|being|trying|talking|"
                r"lying|asking|saying|playing|running|coming|working|looking|"
                r"getting)\b)"
            ),
            "replacement": "you are ",
        },
        {
            "pattern": r"\bur\b",
            "replacement": "your",
        },
        {
            "pattern": r"\bvas\b",
            "replacement": "what's up",
        },
    )

    def __init__(self, rules_path: Optional[Path] = DEFAULT_NORMALIZATION_RULES_PATH):
        self.replacements = self._load_replacements(rules_path)

    def normalize(self, request: TranslationRequest) -> TextNormalization:
        if request.pair.source.casefold() not in self.source_languages:
            return TextNormalization(request.text)

        normalized_text = request.text
        for pattern, replacement in self.replacements:
            normalized_text = pattern.sub(replacement, normalized_text)

        if normalized_text == request.text:
            return TextNormalization(request.text)

        return TextNormalization(
            normalized_text,
            notes=("Normalized casual English before translation.",),
        )

    @classmethod
    def _load_replacements(cls, rules_path: Optional[Path]):
        rules = cls._FALLBACK_RULES
        if rules_path is not None:
            try:
                with Path(rules_path).open(encoding="utf-8") as rules_file:
                    data = json.load(rules_file)
                rules = data["rules"]
            except (OSError, json.JSONDecodeError, KeyError, TypeError):
                log.warning(
                    "Failed to load translation normalization rules from %s; "
                    "using built-in fallback rules.",
                    rules_path,
                    exc_info=True,
                )

        replacements = []
        for rule in rules:
            try:
                replacements.append(
                    (
                        re.compile(rule["pattern"], re.IGNORECASE),
                        rule["replacement"],
                    )
                )
            except (KeyError, TypeError, re.error):
                log.warning("Skipping invalid translation normalization rule: %r", rule)

        return tuple(replacements)


class SlangAwareTranslationProvider:
    def __init__(self, provider: TranslationProvider, normalizer=None):
        self.provider = provider
        self.normalizer = normalizer or CasualEnglishNormalizer()
        self.name = provider.name

    def supports(self, pair: LanguagePair) -> bool:
        return self.provider.supports(pair)

    def warmup_sync(self) -> None:
        warmup_sync = getattr(self.provider, "warmup_sync", None)
        if warmup_sync is not None:
            warmup_sync()

    def translate_sync(self, request: TranslationRequest) -> TranslationResult:
        normalization = self.normalizer.normalize(request)
        provider_request = request
        if normalization.text != request.text:
            provider_request = TranslationRequest(
                text=normalization.text,
                pair=request.pair,
                context=request.context,
            )

        result = self.provider.translate_sync(provider_request)
        if not normalization.notes:
            return result

        return TranslationResult(
            translated_text=result.translated_text,
            provider=result.provider,
            source_text=request.text,
            pair=result.pair,
            alternatives=result.alternatives,
            notes=result.notes + normalization.notes,
        )


class GeminiTranslateProvider:
    BASE_URL = "https://generativelanguage.googleapis.com/v1beta"
    name = "gemini"

    def __init__(
        self,
        language_pairs: Iterable[LanguagePair],
        *,
        api_key: str,
        model: str,
        timeout_seconds: float = 4.0,
    ):
        self.language_pairs = {
            (pair.source.casefold(), pair.target.casefold()) for pair in language_pairs
        }
        self.api_key = api_key
        self.model = model.strip()
        self.timeout_seconds = timeout_seconds

    def supports(self, pair: LanguagePair) -> bool:
        return (pair.source.casefold(), pair.target.casefold()) in self.language_pairs

    def warmup_sync(self) -> None:
        return None

    def translate_sync(self, request: TranslationRequest) -> TranslationResult:
        if not self.api_key or not self.model:
            raise TranslationError(
                "Gemini translation requires WRITING_FEEDBACK_GEMINI_API_KEY "
                "and WRITING_FEEDBACK_GEMINI_MODEL."
            )

        response = requests.post(
            self.endpoint_for_model(self.model),
            headers={
                "x-goog-api-key": self.api_key,
                "Content-Type": "application/json",
            },
            json={
                "system_instruction": {
                    "parts": [
                        {
                            "text": (
                                "You are a translation engine. Return only JSON. "
                                "Preserve names, links, emojis, punctuation, tone, "
                                "and Discord-style casualness."
                            )
                        }
                    ],
                },
                "contents": [
                    {
                        "role": "user",
                        "parts": [
                            {
                                "text": (
                                    f"Translate from {request.pair.source} to "
                                    f"{request.pair.target}:\n{request.text}\n\n"
                                    'Return exactly: {"translated_text":"..."}'
                                )
                            }
                        ],
                    }
                ],
                "generationConfig": {
                    "temperature": 0.1,
                    "maxOutputTokens": 1024,
                    "responseMimeType": "application/json",
                    "responseSchema": {
                        "type": "object",
                        "properties": {
                            "translated_text": {
                                "type": "string",
                                "description": "The translated text.",
                            }
                        },
                        "required": ["translated_text"],
                    },
                },
            },
            timeout=self.timeout_seconds,
        )

        try:
            response.raise_for_status()
        except requests.HTTPError as exc:
            raise TranslationError("Gemini failed to translate text.") from exc

        try:
            translated_text = self.translated_text_from_payload(response.json())
        except (KeyError, TypeError, json.JSONDecodeError) as exc:
            raise TranslationError("Gemini returned an invalid translation.") from exc

        if not translated_text:
            raise TranslationError("Gemini returned an empty translation.")

        return TranslationResult(
            translated_text=translated_text,
            provider=self.name,
            source_text=request.text,
            pair=request.pair,
        )

    @classmethod
    def translated_text_from_payload(cls, payload: dict) -> str:
        content = cls.content_from_payload(payload)
        data = json.loads(content)
        return str(data.get("translated_text") or "").strip()

    @staticmethod
    def content_from_payload(payload: dict) -> str:
        candidates = payload.get("candidates") or []
        parts = candidates[0]["content"].get("parts") or []
        return str(parts[0].get("text") or "")

    @classmethod
    def endpoint_for_model(cls, model: str) -> str:
        return f"{cls.BASE_URL}/models/{model}:generateContent"


class ArgosTranslateProvider:
    name = "argos"

    def __init__(self, language_pairs: Iterable[LanguagePair]):
        self.language_pairs = {
            (pair.source.casefold(), pair.target.casefold()) for pair in language_pairs
        }

    def supports(self, pair: LanguagePair) -> bool:
        return (pair.source.casefold(), pair.target.casefold()) in self.language_pairs

    def warmup_sync(self) -> None:
        try:
            import argostranslate.translate
        except ImportError as exc:
            raise TranslationError(
                "Argos Translate is not installed. Install argostranslate and the "
                "required language models."
            ) from exc

        installed_languages = argostranslate.translate.get_installed_languages()
        for source_lang, target_lang in self.language_pairs:
            source = self._find_installed_language(installed_languages, source_lang)
            target = self._find_installed_language(installed_languages, target_lang)
            if source is None or target is None:
                continue
            source.get_translation(target)

    def translate_sync(self, request: TranslationRequest) -> TranslationResult:
        try:
            import argostranslate.translate
        except ImportError as exc:
            raise TranslationError(
                "Argos Translate is not installed. Install argostranslate and the "
                "required language models."
            ) from exc

        try:
            translated_text = argostranslate.translate.translate(
                request.text,
                request.pair.source,
                request.pair.target,
            )
        except Exception as exc:
            raise TranslationError(
                f"Argos failed to translate {request.pair.source} -> "
                f"{request.pair.target}."
            ) from exc

        return TranslationResult(
            translated_text=translated_text,
            provider=self.name,
            source_text=request.text,
            pair=request.pair,
        )

    @staticmethod
    def _find_installed_language(installed_languages, code: str):
        normalized_code = code.casefold()
        for language in installed_languages:
            if getattr(language, "code", "").casefold() == normalized_code:
                return language
        return None
