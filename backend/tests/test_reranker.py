"""Reranker adapter, configuration selection and failure-boundary tests."""

from __future__ import annotations

import httpx
import pytest

from app.core.config import settings
from app.modules.routing.reranker import CohereReranker, RerankerError, get_reranker


def _client_factory(handler):
    def factory(**kwargs: object) -> httpx.Client:
        return httpx.Client(transport=httpx.MockTransport(handler), **kwargs)

    return factory


def test_cohere_rerank_aligns_scores_by_document_index() -> None:
    seen: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["authorization"] = request.headers["Authorization"]
        import json

        seen["json"] = json.loads(request.content)
        # Returned out of order: alignment must be by index, not position.
        return httpx.Response(
            200,
            json={
                "results": [
                    {"index": 2, "relevance_score": 0.9},
                    {"index": 0, "relevance_score": 0.5},
                    {"index": 1, "relevance_score": 0.1},
                ]
            },
        )

    reranker = CohereReranker(
        api_key="secret-rerank-key",
        model="rerank-test-model",
        client_factory=_client_factory(handler),
    )
    result = reranker.rerank(query="post text", documents=["a", "b", "c"])

    assert result.provider == "cohere"
    assert result.model == "rerank-test-model"
    assert result.scores == [0.5, 0.1, 0.9]
    assert seen["authorization"] == "Bearer secret-rerank-key"
    body = seen["json"]
    assert body["documents"] == ["a", "b", "c"]
    assert body["top_n"] == 3
    assert body["query"] == "post text"


def test_cohere_rerank_failure_does_not_leak_secrets_or_text() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, text="provider internal error")

    reranker = CohereReranker(
        api_key="do-not-leak",
        model="rerank-test-model",
        client_factory=_client_factory(handler),
    )
    with pytest.raises(RerankerError) as exc:
        reranker.rerank(query="sensitive query text", documents=["doc"])

    message = str(exc.value)
    assert "do-not-leak" not in message
    assert "sensitive query text" not in message


def test_cohere_rerank_rejects_incomplete_results() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        # Only one score for two documents.
        return httpx.Response(200, json={"results": [{"index": 0, "relevance_score": 0.4}]})

    reranker = CohereReranker(
        api_key="key",
        model="rerank-test-model",
        client_factory=_client_factory(handler),
    )
    with pytest.raises(RerankerError):
        reranker.rerank(query="q", documents=["a", "b"])


def test_unconfigured_instance_refuses_to_rerank() -> None:
    reranker = CohereReranker(api_key="", model="")
    with pytest.raises(RerankerError):
        reranker.rerank(query="q", documents=["a"])


def test_get_reranker_is_none_with_default_configuration() -> None:
    # Unit-test defaults: no Cohere key and no model configured.
    assert get_reranker() is None


def test_get_reranker_returns_cohere_when_configured(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "cohere_api_key", "configured-key")
    monkeypatch.setattr(settings, "reranker_model", "rerank-v3.5")
    monkeypatch.setattr(settings, "reranker_provider", "cohere")

    reranker = get_reranker()

    assert isinstance(reranker, CohereReranker)
    assert reranker.name == "cohere"
    assert reranker.model == "rerank-v3.5"


def test_get_reranker_is_none_for_unsupported_provider(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "cohere_api_key", "configured-key")
    monkeypatch.setattr(settings, "reranker_model", "rerank-v3.5")
    monkeypatch.setattr(settings, "reranker_provider", "unknown-vendor")

    assert get_reranker() is None
