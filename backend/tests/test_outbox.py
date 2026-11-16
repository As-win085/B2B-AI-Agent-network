"""Transactional outbox: atomic write, ordered relay, retry and recovery."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from unittest.mock import patch
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.events.outbox import (
    POST_PUBLISHED,
    OutboxEvent,
    OutboxStatus,
    record_event,
)
from app.events.publisher import (
    POST_PUBLISHED_STREAM,
    event_fields,
    publish_pending,
)
from app.modules.posts import service as posts_service
from app.modules.posts.models import Post, PostStatus

_BASE_TIME = datetime(2026, 11, 16, 12, 0, 0, tzinfo=UTC)


class _FakePublisher:
    """Captures published events; optionally fails at a given position."""

    def __init__(self, *, fail_at: int | None = None) -> None:
        self._fail_at = fail_at
        self.published: list[tuple[str, dict[str, str]]] = []

    def publish(self, stream: str, event: dict[str, str]) -> str:
        if self._fail_at is not None and len(self.published) == self._fail_at:
            raise ConnectionError("redis unavailable")
        self.published.append((stream, dict(event)))
        return f"{len(self.published)}-0"


def _processing_post(db: Session) -> Post:
    post = Post(
        organization_id=uuid4(),
        author_agent_id=uuid4(),
        title="Outbox post",
        content="Content that will be published.",
        status=PostStatus.PROCESSING.value,
        embedding_generation=1,
    )
    db.add(post)
    db.commit()
    db.refresh(post)
    return post


def _seed_event(
    db: Session,
    *,
    event_type: str = POST_PUBLISHED,
    offset_seconds: int = 0,
    aggregate_id: UUID | None = None,
) -> OutboxEvent:
    event = record_event(
        db,
        aggregate_type="post",
        aggregate_id=aggregate_id or uuid4(),
        event_type=event_type,
        payload={"post_id": str(aggregate_id or uuid4())},
    )
    event.created_at = _BASE_TIME + timedelta(seconds=offset_seconds)
    db.commit()
    db.refresh(event)
    return event


def _reload(db: Session, event_id: UUID) -> OutboxEvent:
    db.expire_all()
    loaded = db.scalar(select(OutboxEvent).where(OutboxEvent.id == event_id))
    assert loaded is not None
    return loaded


def test_publishing_a_post_records_its_outbox_event_atomically(db: Session) -> None:
    post = _processing_post(db)

    published = posts_service.finish_embedding(
        db,
        post_id=post.id,
        generation=1,
        vector=[0.1] * 4,
        provider="openai",
        model="test-model",
    )

    assert published is True
    db.expire_all()
    refreshed = db.scalar(select(Post).where(Post.id == post.id))
    assert refreshed is not None
    assert refreshed.status == PostStatus.PUBLISHED.value

    events = list(db.scalars(select(OutboxEvent).where(OutboxEvent.aggregate_id == post.id)))
    assert len(events) == 1
    event = events[0]
    assert event.event_type == POST_PUBLISHED
    assert event.aggregate_type == "post"
    assert event.status == OutboxStatus.PENDING.value
    assert event.attempts == 0
    payload = event.payload
    assert payload["post_id"] == str(post.id)
    assert payload["organization_id"] == str(post.organization_id)
    assert payload["author_agent_id"] == str(post.author_agent_id)
    assert payload["embedding_generation"] == 1


def test_failed_embedding_records_no_event(db: Session) -> None:
    post = _processing_post(db)

    failed = posts_service.fail_embedding(
        db, post_id=post.id, generation=1, failure_code="embedding_unavailable"
    )

    assert failed is True
    assert list(db.scalars(select(OutboxEvent).where(OutboxEvent.aggregate_id == post.id))) == []


def test_relay_publishes_pending_events_in_creation_order(db: Session) -> None:
    first = _seed_event(db, offset_seconds=0)
    second = _seed_event(db, offset_seconds=1)
    third = _seed_event(db, offset_seconds=2)
    publisher = _FakePublisher()

    published = publish_pending(db, publisher=publisher, limit=100)

    assert published == 3
    assert [stream for stream, _ in publisher.published] == [POST_PUBLISHED_STREAM] * 3
    assert [fields["event_id"] for _, fields in publisher.published] == [
        str(first.id),
        str(second.id),
        str(third.id),
    ]
    for event in (first, second, third):
        loaded = _reload(db, event.id)
        assert loaded.status == OutboxStatus.PUBLISHED.value
        assert loaded.attempts == 1
        assert loaded.published_at is not None
        assert loaded.last_error is None

    # The wire format round-trips the payload for consumers.
    fields = publisher.published[0][1]
    assert json.loads(fields["payload"])["post_id"] == first.payload["post_id"]
    assert fields["event_type"] == POST_PUBLISHED
    assert fields["aggregate_type"] == "post"
    assert fields["created_at"] == first.created_at.isoformat()


def test_relay_failure_keeps_committed_events_pending_for_retry(db: Session) -> None:
    """Release gate 3: no committed event is lost during publisher outages."""
    first = _seed_event(db, offset_seconds=0)
    second = _seed_event(db, offset_seconds=1)

    outage = publish_pending(db, publisher=_FakePublisher(fail_at=0), limit=100)
    assert outage == 0

    first_loaded = _reload(db, first.id)
    second_loaded = _reload(db, second.id)
    assert first_loaded.status == OutboxStatus.PENDING.value
    assert first_loaded.attempts == 1
    assert "ConnectionError" in (first_loaded.last_error or "")
    # The batch stopped at the first failure so ordering is preserved.
    assert second_loaded.status == OutboxStatus.PENDING.value
    assert second_loaded.attempts == 0

    # Recovery: the next relay run publishes both, oldest first.
    publisher = _FakePublisher()
    recovered = publish_pending(db, publisher=publisher, limit=100)
    assert recovered == 2
    assert [fields["event_id"] for _, fields in publisher.published] == [
        str(first.id),
        str(second.id),
    ]
    assert _reload(db, first.id).attempts == 2


def test_relay_stops_at_failure_to_preserve_per_aggregate_order(db: Session) -> None:
    _seed_event(db, offset_seconds=0)
    second = _seed_event(db, offset_seconds=1)

    published = publish_pending(db, publisher=_FakePublisher(fail_at=1), limit=100)

    assert published == 1
    loaded = _reload(db, second.id)
    assert loaded.status == OutboxStatus.PENDING.value
    assert loaded.attempts == 1


def test_unmapped_event_type_does_not_poison_the_relay(db: Session) -> None:
    mystery = _seed_event(db, event_type="mystery.event", offset_seconds=0)
    valid = _seed_event(db, offset_seconds=1)
    publisher = _FakePublisher()

    published = publish_pending(db, publisher=publisher, limit=100)

    assert published == 0
    assert publisher.published == []
    mystery_loaded = _reload(db, mystery.id)
    assert mystery_loaded.status == OutboxStatus.PENDING.value
    assert mystery_loaded.last_error == "unmapped_event_type"
    # The valid event behind it stays untouched for the next run.
    assert _reload(db, valid.id).attempts == 0


def test_relay_respects_the_batch_limit(db: Session) -> None:
    _seed_event(db, offset_seconds=0)
    _seed_event(db, offset_seconds=1)
    _seed_event(db, offset_seconds=2)
    publisher = _FakePublisher()

    published = publish_pending(db, publisher=publisher, limit=2)

    assert published == 2
    assert len(publisher.published) == 2


def test_embed_and_publish_writes_outbox_and_triggers_relay(
    db: Session, sqlite_session_factory
) -> None:
    from app.core.config import settings
    from app.modules.embeddings.provider import EmbeddingResult
    from app.workers.post_tasks import embed_and_publish

    post = _processing_post(db)

    class _Provider:
        def embed(self, text: str) -> EmbeddingResult:
            return EmbeddingResult(
                provider="openai",
                model=settings.embedding_model,
                vector=[0.01] * settings.embedding_dimensions,
            )

    with (
        patch("app.workers.post_tasks.SessionLocal", sqlite_session_factory),
        patch("app.workers.post_tasks.get_embedding_provider", lambda: _Provider()),
        patch("app.workers.post_tasks.trigger_publish_outbox") as trigger,
    ):
        embed_and_publish(str(post.id), 1)

    events = list(db.scalars(select(OutboxEvent).where(OutboxEvent.aggregate_id == post.id)))
    assert len(events) == 1
    assert events[0].status == OutboxStatus.PENDING.value
    trigger.assert_called_once()

    # A stale generation neither publishes nor emits an event.
    trigger.reset_mock()
    stale_post = _processing_post(db)
    with (
        patch("app.workers.post_tasks.SessionLocal", sqlite_session_factory),
        patch("app.workers.post_tasks.get_embedding_provider", lambda: _Provider()),
        patch("app.workers.post_tasks.trigger_publish_outbox") as stale_trigger,
    ):
        embed_and_publish(str(stale_post.id), 99)
    stale_trigger.assert_not_called()
    assert (
        list(db.scalars(select(OutboxEvent).where(OutboxEvent.aggregate_id == stale_post.id))) == []
    )


def test_event_fields_serialization_is_string_only() -> None:
    event = OutboxEvent(
        aggregate_type="post",
        aggregate_id=uuid4(),
        event_type=POST_PUBLISHED,
        payload={"post_id": str(uuid4()), "embedding_generation": 1},
        created_at=_BASE_TIME,
    )
    fields = event_fields(event)

    assert all(isinstance(value, str) for value in fields.values())
    assert json.loads(fields["payload"])["embedding_generation"] == 1
