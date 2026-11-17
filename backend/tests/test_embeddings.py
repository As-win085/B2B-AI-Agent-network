"""Embedding vector and provider boundary tests."""

from __future__ import annotations

import httpx
import pytest

from app.modules.embeddings.provider import (
    EmbeddingProviderError,
    OpenAIEmbeddingProvider,
    validate_embedding,
)


def test_validate_embedding_rejects_bad_size_and_non_finite_values():
    with pytest.raises(EmbeddingProviderError):
        validate_embedding([0.1], 2)
    with pytest.raises(EmbeddingProviderError):
        validate_embedding([0.1, float("nan")], 2)


def test_openai_provider_parses_vector_without_exposing_key():
    seen: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["authorization"] = request.headers["Authorization"]
        return httpx.Response(
            200,
            json={"model": "test-model", "data": [{"embedding": [0.25, -0.5]}]},
        )

    def client_factory(**kwargs: object) -> httpx.Client:
        return httpx.Client(transport=httpx.MockTransport(handler), **kwargs)

    result = OpenAIEmbeddingProvider(
        api_key="secret-test-key",
        model="test-model",
        dimensions=2,
        client_factory=client_factory,
    ).embed("text to embed")
    assert result.vector == [0.25, -0.5]
    assert result.provider == "openai"
    assert seen["authorization"] == "Bearer secret-test-key"


def test_openai_provider_failure_does_not_include_credentials():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, text="provider internal error")

    def client_factory(**kwargs: object) -> httpx.Client:
        return httpx.Client(transport=httpx.MockTransport(handler), **kwargs)

    provider = OpenAIEmbeddingProvider(
        api_key="do-not-leak", dimensions=2, client_factory=client_factory
    )
    with pytest.raises(EmbeddingProviderError) as exc:
        provider.embed("private post body")
    assert "do-not-leak" not in str(exc.value)
    assert "private post body" not in str(exc.value)
