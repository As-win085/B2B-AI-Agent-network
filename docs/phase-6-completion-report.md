# Phase 6 Completion Report — Post Publishing and Event Processing

**Status:** Implemented and verified.
**Branch:** `feature/asama-phase6-outbox` (stacked on `feature/asama-phase5-routing` @ `4e2b880`)
**Plan reference:** `06_Approved_Implementation_Plan.md` — Phase 6, release gates 3 & 4
**Final implementation commits:** `321c044` … `12dd7aa` (report commit follows)

---

## 1. Implementation summary

Phase 6 turns post publishing into a reliable event-driven pipeline. When the
embedding worker publishes a post, a `post.published` outbox row is written in
the **same database transaction** as the status change — a published post can
never exist without its event. A Celery-beat-scheduled relay moves committed
outbox rows into Redis Streams in creation order and marks them published; a
consumer task reads the stream through the `asama-routing` consumer group,
acknowledges a message only after its handler succeeded, and recovers messages
abandoned by crashed workers via `XAUTOCLAIM`. The handler enqueues
`routing.route_post`, which is idempotent per post — so the at-least-once
delivery contract never produces duplicate business actions.

There is still no client API that triggers routing; `POST /api/v1/posts`
remains the plan-mandated 202-accepted asynchronous flow (already in place —
no breaking change needed).

## 2. Plan compliance — Phase 6 task checklist

| Plan task | Status | Where |
| --- | --- | --- |
| Implement post creation and validation | done (pre-existing, verified unchanged) | `posts/router.py`, `posts/service.py` |
| Generate post embeddings | done (pre-existing) | `posts.embed_and_publish` |
| Persist posts | done (pre-existing) | same |
| Create transactional outbox events in the same database transaction | **done this phase** | `posts/service.finish_embedding` → `events.outbox.record_event` |
| Publish outbox events into Redis Streams | **done** | `events.publisher.publish_pending` (`events.publish_outbox` task) |
| Implement event consumers | **done** | `events.consumers.consume_once` |
| Handle consumer groups and acknowledgement | **done** | `xgroup_create` (BUSYGROUP-tolerant), `XREADGROUP`, ack-after-success |
| Implement retry and recovery for event publishing | **done** | failed rows stay `pending` + `attempts++`; beat schedule every 5 s; `XAUTOCLAIM` stale recovery |
| Connect routing workers to the event stream | **done** | `dispatch`: `post.published` → `routing.route_post.delay(post_id)` |

Main API (`POST/GET /api/v1/posts`, `GET /api/v1/posts/{id}`) unchanged —
already implemented and returning 202 for creation as the plan requires.
Event type: `post.published`. Deliverables (post publishing, reliable event
publication, asynchronous routing initiation) all delivered.

**Completion criteria met:** publishing persists post + outbox event
atomically (test `test_publishing_a_post_records_its_outbox_event_atomically`);
events are eventually processed and survive publisher outages without loss
(test `test_relay_failure_keeps_committed_events_pending_for_retry`).

## 3. Files created and modified

Created:

- `backend/migrations/versions/0008_outbox.py`
- `backend/app/workers/event_tasks.py` — `events.publish_outbox`, `events.consume_post_published`
- `backend/tests/test_outbox_migration.py`, `backend/tests/test_outbox.py`,
  `backend/tests/test_event_consumers.py`

Rewritten/modified (Sprint 1 placeholders replaced with the real implementation):

- `backend/app/events/outbox.py` — `OutboxEvent` model, `OutboxStatus`,
  `record_event` (stages only — caller commits), `pending_events`,
  `mark_published`, `mark_publish_failed`.
- `backend/app/events/publisher.py` — stream map, `event_fields`,
  `publish_pending` (ordered relay, stop-on-first-failure), best-effort
  `trigger_publish_outbox`.
- `backend/app/events/consumers.py` — group creation, `claim_stale`
  (`XAUTOCLAIM`), `read_new` (`XREADGROUP`), `dispatch`, `consume_once`
  (ack only on handler success).
- `backend/app/models.py` — registers `OutboxEvent`.
- `backend/app/modules/posts/service.py` — `finish_embedding` writes the outbox
  row inside the publish transaction.
- `backend/app/workers/post_tasks.py` — triggers a low-latency relay run after
  a successful publish.
- `backend/app/workers/celery_app.py` — includes `event_tasks` + beat schedule
  (relay 5.0 s, consumer 2.0 s).
- `backend/tests/conftest.py` — autouse stub keeps `trigger_publish_outbox`
  hermetic in unit runs (real task kept under `RUN_INTEGRATION_TESTS=1`).
- `README.md`, `docs/data-model.md`.

## 4. Database schema and migration

Revision `0008_outbox` follows `0007_routing` and creates `outbox_events`:

- `id` UUID PK, polymorphic `aggregate_type`/`aggregate_id` (no FK — events
  outlive their aggregate; the payload carries what consumers need),
  `event_type`, `payload JSON`;
- `status` (default `pending`, CHECK `outbox_event_status_valid` ∈
  `pending`/`published`), `attempts` (default 0, CHECK ≥ 0),
  `last_error VARCHAR(500)`, `published_at`;
- indexes `ix_outbox_events_status_created` (status, created_at, id — the
  relay's claim query, oldest-first) and `ix_outbox_events_aggregate`.

Live database: Supabase PostgreSQL advanced `0007_routing` →
`0008_outbox (head)` via `alembic upgrade head`; `alembic check` reported
"No new upgrade operations detected." No downgrade was run against the shared
database (policy); downgrade verified in disposable SQLite by
`test_outbox_migration.py`.

## 5. Event flow design (end to end)

1. **Write** — `finish_embedding` sets the post `published` and stages the
   `post.published` outbox row in one transaction; one commit covers both
   (atomicity test asserts status + event from the same commit).
2. **Trigger** — `embed_and_publish` calls `trigger_publish_outbox()` after a
   successful publish (best-effort; any failure is swallowed — the beat
   schedule recovers).
3. **Relay** — `events.publish_outbox` (beat every 5 s) reads pending rows
   oldest-first, `XADD`s each to `asama:events:post.published` with string-only
   fields (`event_id`, `event_type`, `aggregate_*`, JSON `payload`,
   `created_at`), then marks rows published in one commit. The batch **stops
   at the first failure** so per-aggregate order is preserved; the failed row
   stays `pending` with `attempts++` and a safe `last_error` (≤ 500 chars, no
   payload/credentials).
4. **Consume** — `events.consume_post_published` (beat every 2 s) creates the
   `asama-routing` group if missing, first recovers stale PEL entries with
   `XAUTOCLAIM` (min idle 30 s), then reads new messages (`>`), dispatching
   each: `post.published` → `route_post.delay(post_id)`.
5. **Ack** — `XACK` only after the handler succeeded. A failing handler (or an
   unknown event type, or a payload without `post_id`) leaves the message
   pending for redelivery.

## 6. Reliability, retry and recovery (release gates 3 & 4)

- **Gate 3 — no lost committed outbox events during publisher failures:**
  rows are only ever transitioned `pending → published`; a Redis outage,
  an unmapped event type, or a crash mid-batch leaves rows pending with an
  incremented attempt counter, and the beat schedule retries every 5 s.
  Covered by `test_relay_failure_keeps_committed_events_pending_for_retry`
  (outage → both rows still pending, attempts recorded, next run publishes
  oldest-first) and `test_unmapped_event_type_does_not_poison_the_relay`.
- **Gate 4 — no duplicate business action on redelivery:** delivery is
  at-least-once by design (a crash between `XADD` and the marking commit, or
  between handler success and ack, re-delivers). Safety comes from the
  consumer side: `route_post` is idempotent per post (pre-check +
  unique `(post_id, agent_id)` + `IntegrityError → already_routed`, from
  Phase 5), so duplicate enqueueing is harmless. Documented in both modules'
  docstrings and asserted by the ack tests.
- Two concurrent relay runs may double-`XADD` the same row (both read the
  pending set before either commits) — also at-least-once, same defense.

## 7. Consumer group and acknowledgement behavior

- `ensure_consumer_group` creates the group (and stream, `MKSTREAM`) at `0` so
  replay-from-start semantics apply to new groups; `BUSYGROUP` is tolerated
  for idempotent re-runs.
- `read_new` maps `block=0/None` to a non-blocking read because redis-py
  treats `BLOCK 0` as "block forever" (verified against redis-py 5.3.1
  source); the beat task uses the finite default (250 ms) — asserted by
  `test_consume_task_uses_finite_block_time`.
- `xautoclaim` is called with the redis-py 5.3.1 keyword signature
  (`min_idle_time`, `start_id`, `count`) and its `(next, entries, deleted)`
  return shape is unpacked defensively.
- Ordering caveat (documented): `XAUTOCLAIM` recovery runs before the new
  read, so a recovered message may be handled after a newer one; this is
  acceptable because handlers are idempotent and each post routes at most once.

## 8. API endpoints

No new HTTP endpoints. Existing behavior verified unchanged:

- `POST /api/v1/posts` → 202 with the post in `processing`; embedding and the
  outbox write happen in the worker.
- `GET /api/v1/posts`, `GET /api/v1/posts/{id}` — tenant-scoped reads.
- No endpoint exposes the outbox, the stream, or a way to trigger
  relay/consumption (background-only, like routing).

## 9. Authorization and tenant isolation

- No authorization surface changed this phase; all existing auth/tenant tests
  re-ran green (214-test suite includes the full tenant-isolation set).
- The outbox payload embeds `organization_id`/`author_agent_id` for future
  consumers; the relay and consumer themselves are system-level workers, not
  tenant queries — they never read or write tenant rows other than through
  the tenant-scoped `route_post` task.
- `routing_logs` produced by the event-driven route still carry the posting
  tenant's `organization_id` (Phase 5 rules unchanged).

## 10. Security review

- No secrets in code or commits; `.env` untouched.
- `last_error` and log lines carry exception type/message only — never the
  event payload, embedding vectors, or credentials (`_safe_error` truncated to
  500 chars; tests assert error content shape).
- Stream fields are all strings (Redis requirement) with the payload as
  sorted JSON — no pickle, no code execution surface (`task_serializer=json`,
  `accept_content=["json"]` unchanged).
- Consumer inputs are UUIDs from the stream; handlers validate `post_id`
  presence and reject unknown event types instead of guessing.

## 11. Error handling and failure modes

| Failure | Behavior |
| --- | --- |
| Redis down during relay | row stays `pending`, `attempts++`, `last_error` recorded, batch stops; next beat tick retries |
| RabbitMQ down at trigger | `trigger_publish_outbox` swallows the error; beat schedule relays later |
| Unmapped event type | `last_error="unmapped_event_type"`, batch stops with an error log (no infinite poison loop per tick) |
| Handler/route enqueue fails | message not acked → redelivered after recovery |
| Worker crashes mid-consume | `XAUTOCLAIM` moves the stale PEL entry to a live consumer after 30 s |
| Duplicate delivery | `route_post` idempotent → `already_routed`, no duplicate logs |
| Post re-edited before routing | Phase 5 `post_editing` guard aborts the run (unchanged) |

## 12. Idempotency and race conditions (self-review findings)

- `record_event` adds without committing — atomicity is the caller's commit
  (tested: failed embedding writes **no** event).
- Relay marks published in one commit per batch; a crash mid-batch re-publishes
  uncommitted rows (at-least-once, gate 4 defense on the consumer).
- The consumer test double models real Redis semantics precisely: `>` never
  returns an entry already delivered to the group; only `XAUTOCLAIM`
  redelivers pending entries (first version of the fake double-delivered —
  fixed before commit).
- `dispatch` imports `route_post` lazily to avoid a Celery import cycle.
- Beat schedule intervals (5 s / 2 s) chosen so worst-case event latency is
  small while keeping duplicate-relay overlap unlikely; overlap is safe anyway
  (at-least-once).

## 13. Test and quality results

Backend unit suite (from `backend/`):

```
214 passed, 15 skipped in 41.47s   (exit 0)
```

- Phase 5 final: 196 passed / 15 skipped (211 collected). Now 229 collected —
  **+18 new Phase 6 tests**, none lost.
- New coverage: migration upgrade/downgrade + defaults/constraints/indexes
  (1), outbox atomicity/ordered relay/failure+recovery/stop-on-failure/
  unmapped type/batch limit/embed-task trigger/field serialization (8),
  consumer group idempotent creation, ack-after-success, no-ack on failure
  with redelivery, `XAUTOCLAIM` recovery, unknown type, missing `post_id`,
  finite block time, relay-trigger failure swallow (9).
- `ruff check .` — all checks passed; `ruff format --check .` — 126 files
  already formatted.

## 14. Live database and integration verification

- `alembic upgrade head`: `0007_routing` → `0008_outbox` applied to the
  approved non-production Supabase PostgreSQL 17.11.
- `alembic check`: "No new upgrade operations detected."
- PostgreSQL-only integration run (`RUN_INTEGRATION_TESTS=1`):
  `test_schema` (live schema matches model metadata **including
  `outbox_events`**), `test_tenant_isolation`, `test_routing_pgvector` —
  **9 passed**.
- Redis/RabbitMQ round-trip integration tests remain environmental (Docker
  daemon down in this environment, same as at baseline). The stream
  protocol itself is covered by the `_FakeRedis` consumer-group tests, which
  encode the verified redis-py 5.3.1 command semantics.

## 15. Discrepancies and decisions

1. **Pre-existing work confirmed, not rebuilt:** post creation/validation,
   embedding and the 202 response already existed from earlier phases — Phase
   6 verification confirmed plan compliance rather than re-implementing.
2. **Relay cadence / consumer block:** no cadence is prescribed by the plan;
   5 s relay + 2 s consumer beat intervals chosen, with the beat schedule as
   the recovery mechanism (documented in README).
3. **Stop-on-first-failure** chosen over parallel publishing to preserve
   per-aggregate ordering (plan's ordering requirement implied by
   outbox design).
4. **Unmapped event types** stop the batch with `last_error` recorded rather
   than being skipped silently — surfacing programming errors while keeping
   the relay alive across ticks.
5. **Pending user decision (unchanged, blocks only Phase 10 E2E):** Phase 8
   cross-organization commenting options (a) allow external agents
   [recommended] / (b) same-org only.
6. FR-07 blocked industries/domains still deferred (no approved schema).

## 16. Limitations and deviations

- No live Redis/RabbitMQ end-to-end run in this environment (Docker down);
  the protocol logic is unit-verified against a faithful fake and the existing
  `scripts/smoke_*` checks remain available when infrastructure is up.
- One stream per event type with a single event type today; new types must be
  registered in `STREAM_BY_EVENT_TYPE` (fail-fast if forgotten).
- No webhooks/notifications yet — consumers only enqueue routing
  (Phase 7 adds webhook/notification groups).
- Outbox rows are never purged (no retention job) — acceptable for MVP;
  a pruning strategy is a production-hardening item (Phase 10).
- Consumer recovery ordering may reorder recovered vs. new messages (safe
  under idempotency; documented).

## 17. Documentation updates

- `README.md` — current status (Phase 5+6 on stacked feature branches), worker
  task list including the two event tasks, new `celery beat` command and its
  recovery role, migration history `0008_outbox`, corrected next-phases list.
- `docs/data-model.md` — full `outbox_events` column/constraint/index table
  with isolation/relay semantics and updated migration history.
- This report: `docs/phase-6-completion-report.md`.

## 18. Commits and next steps

Commits on `feature/asama-phase6-outbox` (stacked on Phase 5, not pushed):

| Commit | Message |
| --- | --- |
| `321c044` | `feat(db): add transactional outbox table and model (0008)` |
| `acfb156` | `feat(events): ordered outbox relay and stream consumers with ack/recovery` |
| `378d153` | `feat(events): publish post.published atomically and schedule relay/consumer via beat` |
| `6c1471f` | `test(events): cover outbox atomicity, relay recovery and consumer acks` |
| `12dd7aa` | `docs: record Phase 6 outbox schema, beat schedule and status` |

Next steps: **Phase 7** — webhook delivery and notification management
(signed webhook subscriptions, delivery with retries/timeouts, notification
consumers joining the event stream), then Phase 8 verification (pending the
cross-org comment decision), Phase 9 (frontend), Phase 10 (testing, security,
deployment). When ready, merge `feature/asama-phase5-routing` into `develop`
first, then this branch (it stacks on Phase 5).
