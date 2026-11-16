"""Background embedding task for post publication."""

from __future__ import annotations

from uuid import UUID

from app.core.config import settings
from app.core.database import SessionLocal
from app.events.publisher import trigger_publish_outbox
from app.modules.embeddings.provider import (
    get_embedding_provider,
    validate_embedding,
)
from app.modules.posts import service
from app.workers.celery_app import celery_app


@celery_app.task(name="posts.embed_and_publish")
def embed_and_publish(post_id: str, generation: int) -> None:
    """Publish only after a valid embedding has been persisted."""
    with SessionLocal() as db:
        snapshot = service.get_processing_snapshot(db, post_id=UUID(post_id), generation=generation)
        if snapshot is None:
            return
        title, content = snapshot
        try:
            provider = get_embedding_provider()
            result = provider.embed(f"{title}\n\n{content}")
            vector = validate_embedding(result.vector, settings.embedding_dimensions)
        except Exception:
            service.fail_embedding(
                db,
                post_id=UUID(post_id),
                generation=generation,
                failure_code="embedding_unavailable",
            )
            return
        published = service.finish_embedding(
            db,
            post_id=UUID(post_id),
            generation=generation,
            vector=vector,
            provider=result.provider,
            model=result.model,
        )
    if published:
        # Low-latency relay run; the beat schedule recovers anything this
        # best-effort trigger misses (outbox rows stay pending until then).
        trigger_publish_outbox()
