"""Reranker provider contract and Cohere adapter.

Routing degrades gracefully when no reranker is configured or the provider
fails: :func:`get_reranker` returns ``None`` and the engine falls back to
vector-similarity ordering, recording the fallback in every routing log
(``rerank_status``) so similarity ranking is never presented as AI reranking.
"""

from __future__ import annotations

import math
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Any, Protocol

import httpx

from app.core.config import settings


class RerankerError(Exception):
    """A safe, non-sensitive reranker failure suitable for task handling."""


@dataclass(frozen=True, slots=True)
class RerankResult:
    provider: str
    model: str
    scores: list[float]


class RerankerProvider(Protocol):
    """One reranker implementation. ``scores`` aligns with the documents order."""

    name: str
    model: str

    def rerank(self, *, query: str, documents: Sequence[str]) -> RerankResult: ...


ClientFactory = Callable[..., Any]


def _validate_scores(values: object, expected: int) -> list[float]:
    if not isinstance(values, list) or len(values) != expected:
        raise RerankerError("The reranker provider returned an invalid score count.")
    scores: list[float] = []
    for value in values:
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise RerankerError("The reranker provider returned an invalid score value.")
        number = float(value)
        if not math.isfinite(number):
            raise RerankerError("The reranker provider returned a non-finite score value.")
        scores.append(number)
    return scores


class CohereReranker:
    """Cohere rerank adapter using the configured model."""

    name = "cohere"

    def __init__(
        self,
        *,
        api_key: str | None = None,
        model: str | None = None,
        client_factory: ClientFactory = httpx.Client,
        timeout_seconds: float = 20,
    ) -> None:
        self._api_key = settings.cohere_api_key if api_key is None else api_key
        self.model = settings.reranker_model if model is None else model
        self._client_factory = client_factory
        self._timeout_seconds = timeout_seconds

    def rerank(self, *, query: str, documents: Sequence[str]) -> RerankResult:
        if not self._api_key or not self.model:
            raise RerankerError("The reranker provider is not configured.")
        if not documents:
            return RerankResult(provider=self.name, model=self.model, scores=[])

        try:
            with self._client_factory(timeout=self._timeout_seconds) as client:
                response = client.post(
                    "https://api.cohere.com/v2/rerank",
                    headers={"Authorization": f"Bearer {self._api_key}"},
                    json={
                        "model": self.model,
                        "query": query,
                        "documents": list(documents),
                        "top_n": len(documents),
                    },
                )
                response.raise_for_status()
                payload = response.json()
                results = payload["results"]
        except RerankerError:
            raise
        except (httpx.HTTPError, KeyError, TypeError, ValueError):
            # Avoid retaining provider responses, query text or credentials in
            # errors and logs. A retry/task can use this stable failure class.
            raise RerankerError("The reranker provider request failed.") from None

        scores = [0.0] * len(documents)
        try:
            if len(results) != len(documents):
                raise RerankerError("The reranker provider returned an incomplete result.")
            for item in results:
                index = int(item["index"])
                scores[index] = float(item["relevance_score"])
        except RerankerError:
            raise
        except (KeyError, TypeError, ValueError, IndexError):
            raise RerankerError("The reranker provider returned an invalid result.") from None
        scores = _validate_scores(scores, len(documents))
        return RerankResult(provider=self.name, model=self.model, scores=scores)


def get_reranker() -> RerankerProvider | None:
    """Return the configured reranker, or ``None`` when reranking is
    unavailable (unconfigured, unsupported provider or missing credentials).

    Callers must treat ``None`` as "degrade to similarity ranking", never as
    an error that blocks routing.
    """
    provider = settings.reranker_provider.strip().lower()
    if provider != "cohere":
        return None
    if not settings.cohere_api_key or not settings.reranker_model.strip():
        return None
    return CohereReranker()
