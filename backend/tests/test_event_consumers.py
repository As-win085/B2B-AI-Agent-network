"""Consumer groups, acknowledgement and recovery for the post.published stream.

A ``_FakeRedis`` stands in for Redis Streams so the group/ack protocol is
exercised deterministically: ack only after the handler succeeded, leave the
message pending when it failed, and recover stale messages via XAUTOCLAIM.
"""

from __future__ import annotations

import json
from unittest.mock import patch

from app.events import consumers
from app.events.publisher import POST_PUBLISHED_STREAM


class _FakeRedis:
    """Minimal Redis Streams emulation for the consumer-group protocol."""

    def __init__(self) -> None:
        self.streams: dict[str, list[tuple[str, dict[str, str]]]] = {}
        self.groups: dict[tuple[str, str], str] = {}  # (stream, group) -> last_id
        self.pending: dict[tuple[str, str], list[str]] = {}  # (stream, group) -> ids
        # Entries ever delivered to the group — XREADGROUP ">" never returns
        # these again (only XAUTOCLAIM redelivers them).
        self.delivered: set[tuple[str, str, str]] = set()
        self.acked: list[tuple[str, str, str]] = []
        self.xadd_count = 0

    # -- server side -----------------------------------------------------
    def xgroup_create(self, stream: str, group: str, id: str = "0", mkstream: bool = False):
        key = (stream, group)
        if key in self.groups:
            from redis.exceptions import ResponseError

            raise ResponseError("BUSYGROUP Consumer Group name already exists")
        if stream not in self.streams and not mkstream:
            from redis.exceptions import ResponseError

            raise ResponseError("no such key")
        self.streams.setdefault(stream, [])
        self.groups[key] = id
        self.pending.setdefault(key, [])

    def xadd(self, stream: str, fields: dict[str, str]) -> str:
        self.xadd_count += 1
        entry_id = f"{self.xadd_count}-0"
        self.streams.setdefault(stream, []).append((entry_id, dict(fields)))
        return entry_id

    def xreadgroup(self, group, consumer, streams, count=None, block=None, noack=False):
        ((stream, _),) = streams.items()
        key = (stream, group)
        entries = [
            entry
            for entry in self.streams.get(stream, [])
            if entry[0] not in self.pending.get(key, [])
            and (stream, group, entry[0]) not in self.delivered
        ]
        if count is not None:
            entries = entries[:count]
        for entry_id, _fields in entries:
            self.pending.setdefault(key, []).append(entry_id)
            self.delivered.add((stream, group, entry_id))
        if not entries:
            return []
        return [[stream, entries]]

    def xautoclaim(self, stream, group, consumer, min_idle_time, start_id="0-0", count=None):
        key = (stream, group)
        entries = [
            entry for entry in self.streams.get(stream, []) if entry[0] in self.pending.get(key, [])
        ]
        if count is not None:
            entries = entries[:count]
        return ["0-0", [list(entry) for entry in entries], []]

    def xack(self, stream, group, *entry_ids):
        key = (stream, group)
        for entry_id in entry_ids:
            self.acked.append((stream, group, entry_id))
            if key in self.pending and entry_id in self.pending[key]:
                self.pending[key].remove(entry_id)
        return len(entry_ids)

    def close(self) -> None:  # pragma: no cover - parity with redis-py
        pass


def _post_published_fields(post_id: str) -> dict[str, str]:
    return {
        "event_id": "evt-1",
        "event_type": "post.published",
        "aggregate_type": "post",
        "aggregate_id": post_id,
        "payload": json.dumps({"post_id": post_id}),
        "created_at": "2026-11-16T12:00:00+00:00",
    }


def test_ensure_consumer_group_is_idempotent() -> None:
    client = _FakeRedis()
    consumers.ensure_consumer_group(client, POST_PUBLISHED_STREAM, consumers.ROUTING_GROUP)  # type: ignore[arg-type]
    consumers.ensure_consumer_group(client, POST_PUBLISHED_STREAM, consumers.ROUTING_GROUP)  # type: ignore[arg-type]
    assert (POST_PUBLISHED_STREAM, consumers.ROUTING_GROUP) in client.groups


def test_ack_only_after_handler_success_and_dispatch_enqueues_routing() -> None:
    client = _FakeRedis()
    entry_id = client.xadd(
        POST_PUBLISHED_STREAM, _post_published_fields("11111111-1111-1111-1111-111111111111")
    )

    with patch("app.workers.routing_tasks.route_post") as route_task:
        handled = consumers.consume_once(client=client, count=10, block_ms=1)  # type: ignore[arg-type]

    assert handled == 1
    assert client.acked == [(POST_PUBLISHED_STREAM, consumers.ROUTING_GROUP, entry_id)]
    assert client.pending[(POST_PUBLISHED_STREAM, consumers.ROUTING_GROUP)] == []
    route_task.delay.assert_called_once_with("11111111-1111-1111-1111-111111111111")


def test_failed_handler_leaves_message_pending_for_redelivery() -> None:
    client = _FakeRedis()
    entry_id = client.xadd(
        POST_PUBLISHED_STREAM, _post_published_fields("22222222-2222-2222-2222-222222222222")
    )

    with patch("app.workers.routing_tasks.route_post") as route_task:
        route_task.delay.side_effect = ConnectionError("broker down")
        handled = consumers.consume_once(client=client, count=10, block_ms=1)  # type: ignore[arg-type]

    assert handled == 0
    assert client.acked == []
    assert entry_id in client.pending[(POST_PUBLISHED_STREAM, consumers.ROUTING_GROUP)]

    # Recovery: once the broker is back, the same message is redelivered and acked.
    with patch("app.workers.routing_tasks.route_post") as route_task:
        route_task.delay.side_effect = None
        recovered = consumers.consume_once(client=client, count=10, block_ms=1)  # type: ignore[arg-type]

    assert recovered == 1
    assert client.acked[-1] == (POST_PUBLISHED_STREAM, consumers.ROUTING_GROUP, entry_id)


def test_stale_pending_message_is_recovered_via_xautoclaim() -> None:
    client = _FakeRedis()
    entry_id = client.xadd(
        POST_PUBLISHED_STREAM, _post_published_fields("33333333-3333-3333-3333-333333333333")
    )
    # A crashed consumer read the message (it is in the PEL) but never acked.
    client.xreadgroup(consumers.ROUTING_GROUP, "crashed", {POST_PUBLISHED_STREAM: ">"})
    assert client.pending[(POST_PUBLISHED_STREAM, consumers.ROUTING_GROUP)] == [entry_id]

    with patch("app.workers.routing_tasks.route_post") as route_task:
        handled = consumers.consume_once(client=client, count=10, block_ms=1)  # type: ignore[arg-type]

    assert handled == 1
    route_task.delay.assert_called_once()
    assert client.acked == [(POST_PUBLISHED_STREAM, consumers.ROUTING_GROUP, entry_id)]


def test_unknown_event_type_is_not_acked() -> None:
    client = _FakeRedis()
    entry_id = client.xadd(POST_PUBLISHED_STREAM, {"event_type": "mystery.event", "payload": "{}"})

    with patch("app.workers.routing_tasks.route_post") as route_task:
        handled = consumers.consume_once(client=client, count=10, block_ms=1)  # type: ignore[arg-type]

    assert handled == 0
    assert client.acked == []
    assert entry_id in client.pending[(POST_PUBLISHED_STREAM, consumers.ROUTING_GROUP)]
    route_task.delay.assert_not_called()


def test_post_published_without_post_id_is_not_acked() -> None:
    client = _FakeRedis()
    fields = _post_published_fields("44444444-4444-4444-4444-444444444444")
    fields["payload"] = json.dumps({})
    entry_id = client.xadd(POST_PUBLISHED_STREAM, fields)

    with patch("app.workers.routing_tasks.route_post") as route_task:
        handled = consumers.consume_once(client=client, count=10, block_ms=1)  # type: ignore[arg-type]

    assert handled == 0
    assert client.acked == []
    assert entry_id in client.pending[(POST_PUBLISHED_STREAM, consumers.ROUTING_GROUP)]
    route_task.delay.assert_not_called()


def test_consume_task_uses_finite_block_time() -> None:
    """BLOCK 0 means "block forever" in Redis — the beat task must not use it."""
    from app.workers import event_tasks

    seen: dict[str, object] = {}

    def _fake_consume_once(**kwargs):
        seen.update(kwargs)
        return 0

    with patch.object(event_tasks, "consume_once", _fake_consume_once):
        result = event_tasks.consume_post_published()

    assert result == {"handled": "0"}
    assert "block_ms" not in seen or seen["block_ms"] != 0


def test_relay_trigger_failure_never_propagates() -> None:
    from app.events import publisher

    with patch("app.workers.event_tasks.publish_outbox") as task:
        task.delay.side_effect = ConnectionError("broker down")
        publisher.trigger_publish_outbox()  # must not raise
    task.delay.assert_called_once()
