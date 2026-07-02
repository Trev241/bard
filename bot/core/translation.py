import asyncio
import hashlib
import json
import logging
import re
import sqlite3
import time
from collections import OrderedDict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable, Optional, Protocol, Sequence, Tuple

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
        self._items: (
            "OrderedDict[Tuple[str, str, str, str, str], TranslationResult]"
        ) = OrderedDict()

    def get(
        self,
        request: TranslationRequest,
        *,
        namespace: str = "",
    ) -> Optional[TranslationResult]:
        if self.max_size == 0:
            return None

        key = self._key(request, namespace=namespace)
        result = self._items.get(key)
        if result is None:
            return None

        self._items.move_to_end(key)
        return result

    def set(
        self,
        request: TranslationRequest,
        result: TranslationResult,
        *,
        namespace: str = "",
    ) -> None:
        if self.max_size == 0:
            return

        key = self._key(request, namespace=namespace)
        self._items[key] = result
        self._items.move_to_end(key)

        while len(self._items) > self.max_size:
            self._items.popitem(last=False)

    @staticmethod
    def _key(
        request: TranslationRequest,
        *,
        namespace: str = "",
    ) -> Tuple[str, str, str, str, str]:
        return (
            namespace.casefold(),
            str(request.context.get("guild_id") or ""),
            request.pair.source.casefold(),
            request.pair.target.casefold(),
            " ".join(request.text.split()),
        )


class SQLiteTranslationCache(TranslationCache):
    def __init__(self, path: Path, max_size: int = 1000):
        super().__init__(max_size=max_size)
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    def get(
        self,
        request: TranslationRequest,
        *,
        namespace: str = "",
    ) -> Optional[TranslationResult]:
        if self.max_size == 0:
            return None

        cache_key = self._sqlite_key(request, namespace=namespace)
        try:
            with self._connect() as connection:
                row = connection.execute(
                    "SELECT payload FROM translation_cache WHERE cache_key = ?",
                    (cache_key,),
                ).fetchone()
                if row is None:
                    return None
                connection.execute(
                    "UPDATE translation_cache SET updated_at = ? WHERE cache_key = ?",
                    (time.time(), cache_key),
                )
        except sqlite3.Error:
            log.warning("Failed to read translation cache.", exc_info=True)
            return None

        try:
            return self._result_from_payload(json.loads(row[0]))
        except (TypeError, ValueError, json.JSONDecodeError):
            log.warning("Skipping invalid cached translation payload.", exc_info=True)
            return None

    def set(
        self,
        request: TranslationRequest,
        result: TranslationResult,
        *,
        namespace: str = "",
    ) -> None:
        if self.max_size == 0:
            return

        cache_key = self._sqlite_key(request, namespace=namespace)
        payload = json.dumps(self._result_to_payload(result), separators=(",", ":"))
        try:
            with self._connect() as connection:
                connection.execute(
                    """
                    INSERT OR REPLACE INTO translation_cache
                        (cache_key, payload, updated_at)
                    VALUES (?, ?, ?)
                    """,
                    (cache_key, payload, time.time()),
                )
                self._prune(connection)
        except sqlite3.Error:
            log.warning("Failed to write translation cache.", exc_info=True)

    def _initialize(self) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS translation_cache (
                    cache_key TEXT PRIMARY KEY,
                    payload TEXT NOT NULL,
                    updated_at REAL NOT NULL
                )
                """
            )

    def _connect(self):
        return sqlite3.connect(self.path)

    def _sqlite_key(self, request: TranslationRequest, *, namespace: str = "") -> str:
        key = json.dumps(
            self._key(request, namespace=namespace),
            ensure_ascii=True,
            separators=(",", ":"),
        )
        return hashlib.sha256(key.encode("utf-8")).hexdigest()

    def _prune(self, connection) -> None:
        connection.execute(
            """
            DELETE FROM translation_cache
            WHERE cache_key IN (
                SELECT cache_key
                FROM translation_cache
                ORDER BY updated_at DESC
                LIMIT -1 OFFSET ?
            )
            """,
            (self.max_size,),
        )

    @staticmethod
    def _result_to_payload(result: TranslationResult) -> dict:
        return {
            "translated_text": result.translated_text,
            "provider": result.provider,
            "source_text": result.source_text,
            "pair": {
                "source": result.pair.source,
                "target": result.pair.target,
            },
            "alternatives": list(result.alternatives),
            "notes": list(result.notes),
        }

    @staticmethod
    def _result_from_payload(payload: dict) -> TranslationResult:
        pair = payload["pair"]
        return TranslationResult(
            translated_text=str(payload["translated_text"]),
            provider=str(payload["provider"]),
            source_text=str(payload["source_text"]),
            pair=LanguagePair(str(pair["source"]), str(pair["target"])),
            alternatives=tuple(str(item) for item in payload.get("alternatives") or ()),
            notes=tuple(str(item) for item in payload.get("notes") or ()),
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
        results = await self.translate_many((request,))
        return results[0]

    async def translate_many(
        self,
        requests: Sequence[TranslationRequest],
    ) -> Tuple[TranslationResult, ...]:
        if not requests:
            return ()

        normalized_requests = []
        for request in requests:
            text = request.text.strip()
            if not text:
                raise TranslationError("Cannot translate an empty message.")
            normalized_requests.append(
                TranslationRequest(
                    text=text,
                    pair=request.pair,
                    context=request.context,
                )
            )

        results = [None] * len(normalized_requests)
        pending_by_namespace = {}
        for index, normalized_request in enumerate(normalized_requests):
            provider = self._select_provider(normalized_request.pair)
            cache_namespace = self._cache_namespace(provider, normalized_request)
            cached = self.cache.get(normalized_request, namespace=cache_namespace)
            if cached is not None:
                results[index] = cached
                continue
            pending_by_namespace.setdefault(
                (id(provider), cache_namespace),
                {
                    "provider": provider,
                    "cache_namespace": cache_namespace,
                    "requests": [],
                    "indexes": [],
                },
            )
            pending_by_namespace[(id(provider), cache_namespace)]["requests"].append(
                normalized_request
            )
            pending_by_namespace[(id(provider), cache_namespace)]["indexes"].append(index)

        for group in pending_by_namespace.values():
            provider = group["provider"]
            group_requests = tuple(group["requests"])
            async with self.semaphore:
                translated = await asyncio.to_thread(
                    self._translate_many_sync,
                    provider,
                    group_requests,
                )

            if len(translated) != len(group_requests):
                raise TranslationError("Provider returned an invalid translation batch.")

            for index, request, result in zip(
                group["indexes"],
                group_requests,
                translated,
            ):
                self.cache.set(request, result, namespace=group["cache_namespace"])
                results[index] = result

        return tuple(result for result in results if result is not None)

    @staticmethod
    def _translate_many_sync(
        provider: TranslationProvider,
        requests: Sequence[TranslationRequest],
    ) -> Tuple[TranslationResult, ...]:
        translate_many_sync = getattr(provider, "translate_many_sync", None)
        if translate_many_sync is not None:
            return tuple(translate_many_sync(tuple(requests)))
        return tuple(provider.translate_sync(request) for request in requests)

    def _select_provider(self, pair: LanguagePair) -> TranslationProvider:
        for provider in self.providers:
            if provider.supports(pair):
                return provider

        raise TranslationError(
            f"No translation provider supports {pair.source!r} -> {pair.target!r}."
        )

    @staticmethod
    def _cache_namespace(
        provider: TranslationProvider,
        request: TranslationRequest,
    ) -> str:
        cache_key_for_request = getattr(provider, "cache_key_for_request", None)
        if cache_key_for_request is not None:
            return str(cache_key_for_request(request))
        return getattr(provider, "name", provider.__class__.__name__)


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

    def translate_many_sync(
        self,
        requests: Sequence[TranslationRequest],
    ) -> Tuple[TranslationResult, ...]:
        provider_requests = []
        original_requests = []
        normalizations = []
        for request in requests:
            normalization = self.normalizer.normalize(request)
            provider_request = request
            if normalization.text != request.text:
                provider_request = TranslationRequest(
                    text=normalization.text,
                    pair=request.pair,
                    context=request.context,
                )
            provider_requests.append(provider_request)
            original_requests.append(request)
            normalizations.append(normalization)

        translate_many_sync = getattr(self.provider, "translate_many_sync", None)
        if translate_many_sync is not None:
            results = tuple(translate_many_sync(tuple(provider_requests)))
        else:
            results = tuple(
                self.provider.translate_sync(provider_request)
                for provider_request in provider_requests
            )

        patched_results = []
        for request, normalization, result in zip(
            original_requests,
            normalizations,
            results,
        ):
            if not normalization.notes:
                patched_results.append(result)
                continue
            patched_results.append(
                TranslationResult(
                    translated_text=result.translated_text,
                    provider=result.provider,
                    source_text=request.text,
                    pair=result.pair,
                    alternatives=result.alternatives,
                    notes=result.notes + normalization.notes,
                )
            )
        return tuple(patched_results)

    def cache_key_for_request(self, request: TranslationRequest) -> str:
        cache_key_for_request = getattr(self.provider, "cache_key_for_request", None)
        provider_key = (
            cache_key_for_request(request)
            if cache_key_for_request is not None
            else self.provider.name
        )
        return f"slang:{provider_key}"


class TranslationProviderRouter:
    name = "router"

    def __init__(self, providers: Iterable[TranslationProvider], routes=None):
        self.providers = list(providers)
        self.routes = {
            (int(guild_id), source.casefold(), target.casefold()): provider.casefold()
            for (guild_id, source, target), provider in (routes or {}).items()
        }

    def supports(self, pair: LanguagePair) -> bool:
        return self._select_provider(pair) is not None

    def warmup_sync(self) -> None:
        for provider in self.providers:
            warmup_sync = getattr(provider, "warmup_sync", None)
            if warmup_sync is not None:
                warmup_sync()

    def translate_sync(self, request: TranslationRequest) -> TranslationResult:
        provider = self._select_provider_for_request(request)

        if provider is None:
            raise TranslationError(
                f"No translation provider supports {request.pair.source!r} -> "
                f"{request.pair.target!r}."
            )
        return provider.translate_sync(request)

    def translate_many_sync(
        self,
        requests: Sequence[TranslationRequest],
    ) -> Tuple[TranslationResult, ...]:
        results = [None] * len(requests)
        grouped = {}
        for index, request in enumerate(requests):
            provider = self._select_provider_for_request(request)
            if provider is None:
                raise TranslationError(
                    f"No translation provider supports {request.pair.source!r} -> "
                    f"{request.pair.target!r}."
                )
            grouped.setdefault(provider, {"indexes": [], "requests": []})
            grouped[provider]["indexes"].append(index)
            grouped[provider]["requests"].append(request)

        for provider, group in grouped.items():
            group_requests = tuple(group["requests"])
            translate_many_sync = getattr(provider, "translate_many_sync", None)
            if translate_many_sync is not None:
                translated = tuple(translate_many_sync(group_requests))
            else:
                translated = tuple(
                    provider.translate_sync(request) for request in group_requests
                )
            for index, result in zip(group["indexes"], translated):
                results[index] = result

        return tuple(result for result in results if result is not None)

    def cache_key_for_request(self, request: TranslationRequest) -> str:
        provider = self._select_provider_for_request(request)
        provider_name = provider.name if provider is not None else "none"
        guild_id = request.context.get("guild_id") or ""
        return (
            f"router:{guild_id}:"
            f"{request.pair.source.casefold()}->{request.pair.target.casefold()}:"
            f"{provider_name.casefold()}"
        )

    def _select_provider_for_request(
        self,
        request: TranslationRequest,
    ) -> Optional[TranslationProvider]:
        provider = self._select_provider(request.pair)
        guild_id = request.context.get("guild_id")
        if guild_id is not None:
            routed_provider = self._select_routed_provider(int(guild_id), request.pair)
            if routed_provider is not None:
                provider = routed_provider
        return provider

    def _select_provider(self, pair: LanguagePair) -> Optional[TranslationProvider]:
        for provider in self.providers:
            if provider.supports(pair):
                return provider
        return None

    def _select_routed_provider(
        self, guild_id: int, pair: LanguagePair
    ) -> Optional[TranslationProvider]:
        provider_name = self.routes.get(
            (guild_id, pair.source.casefold(), pair.target.casefold())
        )
        if not provider_name:
            return None

        for provider in self.providers:
            if provider.name.casefold() == provider_name and provider.supports(pair):
                return provider
        return None


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
        rate_limit_cooldown_seconds: float = 60.0,
        session=None,
    ):
        self.language_pairs = {
            (pair.source.casefold(), pair.target.casefold()) for pair in language_pairs
        }
        self.api_key = api_key
        self.models = tuple(item.strip() for item in model.split(",") if item.strip())
        self.model = self.models[0] if self.models else ""
        self.timeout_seconds = timeout_seconds
        self.rate_limit_cooldown_seconds = max(0.0, rate_limit_cooldown_seconds)
        self.session = session or requests.Session()
        self._cooldown_until = 0.0

    def supports(self, pair: LanguagePair) -> bool:
        return (pair.source.casefold(), pair.target.casefold()) in self.language_pairs

    def warmup_sync(self) -> None:
        return None

    def translate_sync(self, request: TranslationRequest) -> TranslationResult:
        if not self.api_key or not self.models:
            raise TranslationError(
                "Gemini translation requires WRITING_FEEDBACK_GEMINI_API_KEY "
                "and WRITING_FEEDBACK_GEMINI_MODEL."
            )
        if self._is_cooling_down():
            remaining = int(max(1, self._cooldown_until - time.monotonic()))
            raise TranslationError(
                f"Gemini translation rate-limit cooldown active for {remaining}s."
            )

        last_error = None
        rate_limited_responses = []
        for model in self.models:
            try:
                return self._translate_with_model(request, model)
            except TranslationError as exc:
                last_error = exc
                response = getattr(exc.__cause__, "response", None)
                if getattr(response, "status_code", None) == 429:
                    rate_limited_responses.append(response)
                continue

        if rate_limited_responses:
            self._start_rate_limit_cooldown(rate_limited_responses[-1])
        raise TranslationError("Gemini failed to translate text with every model.") from last_error

    def translate_many_sync(
        self,
        requests: Sequence[TranslationRequest],
    ) -> Tuple[TranslationResult, ...]:
        if not requests:
            return ()
        if len(requests) == 1:
            return (self.translate_sync(requests[0]),)
        if not self.api_key or not self.models:
            raise TranslationError(
                "Gemini translation requires WRITING_FEEDBACK_GEMINI_API_KEY "
                "and WRITING_FEEDBACK_GEMINI_MODEL."
            )
        if self._is_cooling_down():
            remaining = int(max(1, self._cooldown_until - time.monotonic()))
            raise TranslationError(
                f"Gemini translation rate-limit cooldown active for {remaining}s."
            )

        last_error = None
        rate_limited_responses = []
        for model in self.models:
            try:
                return self._translate_many_with_model(requests, model)
            except TranslationError as exc:
                last_error = exc
                response = getattr(exc.__cause__, "response", None)
                if getattr(response, "status_code", None) == 429:
                    rate_limited_responses.append(response)
                continue

        if rate_limited_responses:
            self._start_rate_limit_cooldown(rate_limited_responses[-1])
        raise TranslationError("Gemini failed to translate text batch.") from last_error

    def _translate_with_model(
        self,
        request: TranslationRequest,
        model: str,
    ) -> TranslationResult:
        response = self.session.post(
            self.endpoint_for_model(model),
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
            raise TranslationError(
                f"Gemini model {model!r} failed to translate text."
            ) from exc

        try:
            translated_text = self.translated_text_from_payload(response.json())
        except (KeyError, TypeError, json.JSONDecodeError) as exc:
            raise TranslationError("Gemini returned an invalid translation.") from exc

        if not translated_text:
            raise TranslationError(f"Gemini model {model!r} returned an empty translation.")

        return TranslationResult(
            translated_text=translated_text,
            provider=self.name,
            source_text=request.text,
            pair=request.pair,
        )

    def _translate_many_with_model(
        self,
        requests: Sequence[TranslationRequest],
        model: str,
    ) -> Tuple[TranslationResult, ...]:
        pair = requests[0].pair
        if any(request.pair != pair for request in requests):
            return tuple(self._translate_with_model(request, model) for request in requests)

        response = self.session.post(
            self.endpoint_for_model(model),
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
                                "and Discord-style casualness. Translate each item "
                                "independently and keep each id unchanged."
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
                                    f"Translate each item from {pair.source} to "
                                    f"{pair.target}. Return exactly this JSON shape: "
                                    '{"translations":[{"id":"...","translated_text":"..."}]}'
                                    "\n\nItems:\n"
                                    f"{self.batch_items_json(requests)}"
                                )
                            }
                        ],
                    }
                ],
                "generationConfig": {
                    "temperature": 0.1,
                    "maxOutputTokens": max(1024, 512 * len(requests)),
                    "responseMimeType": "application/json",
                    "responseSchema": {
                        "type": "object",
                        "properties": {
                            "translations": {
                                "type": "array",
                                "items": {
                                    "type": "object",
                                    "properties": {
                                        "id": {"type": "string"},
                                        "translated_text": {"type": "string"},
                                    },
                                    "required": ["id", "translated_text"],
                                },
                            }
                        },
                        "required": ["translations"],
                    },
                },
            },
            timeout=self.timeout_seconds,
        )

        try:
            response.raise_for_status()
        except requests.HTTPError as exc:
            raise TranslationError(
                f"Gemini model {model!r} failed to translate text batch."
            ) from exc

        try:
            translations = self.translations_from_payload(response.json())
        except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
            raise TranslationError("Gemini returned an invalid translation batch.") from exc

        results = []
        for index, request in enumerate(requests):
            item_id = self.batch_item_id(index)
            translated_text = translations.get(item_id, "").strip()
            if not translated_text:
                raise TranslationError(
                    f"Gemini omitted translation batch item {item_id!r}."
                )
            results.append(
                TranslationResult(
                    translated_text=translated_text,
                    provider=self.name,
                    source_text=request.text,
                    pair=request.pair,
                )
            )
        return tuple(results)

    @classmethod
    def translated_text_from_payload(cls, payload: dict) -> str:
        content = cls.content_from_payload(payload)
        data = json.loads(content)
        return str(data.get("translated_text") or "").strip()

    @classmethod
    def translations_from_payload(cls, payload: dict) -> dict:
        content = cls.content_from_payload(payload)
        data = json.loads(content)
        translations = data.get("translations") or []
        return {
            str(item.get("id") or ""): str(item.get("translated_text") or "")
            for item in translations
            if isinstance(item, dict)
        }

    @staticmethod
    def content_from_payload(payload: dict) -> str:
        candidates = payload.get("candidates") or []
        parts = candidates[0]["content"].get("parts") or []
        return str(parts[0].get("text") or "")

    @classmethod
    def endpoint_for_model(cls, model: str) -> str:
        return f"{cls.BASE_URL}/models/{model}:generateContent"

    @staticmethod
    def batch_item_id(index: int) -> str:
        return str(index)

    @classmethod
    def batch_items_json(cls, requests: Sequence[TranslationRequest]) -> str:
        return json.dumps(
            [
                {
                    "id": cls.batch_item_id(index),
                    "text": request.text,
                }
                for index, request in enumerate(requests)
            ],
            ensure_ascii=False,
        )

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
        except ImportError:
            log.warning(
                "Argos Translate is not installed. Install argostranslate and the "
                "required language models."
            )
            return

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
