import asyncio
import logging
from collections import OrderedDict
from dataclasses import dataclass, field
from typing import Iterable, Optional, Protocol, Tuple


log = logging.getLogger(__name__)


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


class ArgosTranslateProvider:
    name = "argos"

    def __init__(self, language_pairs: Iterable[LanguagePair]):
        self.language_pairs = {
            (pair.source.casefold(), pair.target.casefold()) for pair in language_pairs
        }

    def supports(self, pair: LanguagePair) -> bool:
        return (pair.source.casefold(), pair.target.casefold()) in self.language_pairs

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
