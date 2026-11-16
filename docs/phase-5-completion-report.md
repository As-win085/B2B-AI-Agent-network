# Phase 5 Completion Report — Embedding Infrastructure and AI Routing

**Status:** Implemented and verified.
**Branch:** `feature/asama-phase5-routing` (from `develop` @ `d1295b0`)
**Plan reference:** `06_Approved_Implementation_Plan.md` — Phase 5, FR-07/08/09/15
**Final implementation commit:** `0e86b2f`

---

## 1. Implementation summary

Phase 5 delivers the core AI feature: versioned agent interest embeddings and
the eight-step semantic routing engine. Agents' interest manifestos are
embedded in the background with a generation guard that makes stale writes
impossible; posts are routed to eligible agents across organizations by
pgvector cosine retrieval (HNSW), optional Cohere reranking, a configurable
score threshold and a recipient limit. Every candidate decision is persisted
in `routing_logs` as an explainable audit record (FR-15). Organizations can
block agents from receiving their posts via a new management API.

There is deliberately **no client API that triggers routing**: the
`routing.route_post` Celery task is the single entry point and will be
enqueued from the `post.published` outbox event in Phase 6.

## 2. Plan compliance — Phase 5 task checklist

| Plan task | Status | Where |
| --- | --- | --- |
| Create an embedding provider interface | done (pre-existing, reused) | `app/modules/embeddings/provider.py` |
| Implement OpenAI embedding adapter | done (pre-existing, reused) | same — one provider implementation in the codebase |
| Generate and store agent interest embeddings | done | `app/modules/embeddings/service.py`, `app/workers/agent_tasks.py` |
| Generate and store post embeddings | done (pre-existing Phase 6-early) | `posts` pipeline, unchanged |
| Implement vector similarity search using pgvector | done | `routing/service.py::_retrieve_candidates` (`<=>` + HNSW) |
| Implement SQL eligibility filtering | done | `routing/service.py::_eligibility_statement` (steps 1–3 in one statement) |
| Implement candidate retrieval | done | top-K with configurable `ROUTING_TOP_K` |
| Integrate the reranking provider | done | `routing/reranker.py` (Cohere v2 adapter) |
| Apply routing threshold and recipient limits | done | `ROUTING_SCORE_THRESHOLD` (inclusive `>=`), `ROUTING_MAX_RECIPIENTS` |
| Save routing decisions and scores | done | `routing_logs`, one row per (post, candidate) |
| Record embedding and model versions | done | agent side: `agent_embedding_versions` + generation; log rows carry provider/model/generation and reranker metadata |
| Recommended 8-step sequence | done | see section 5 |

DB implementation order respected: `agent_embedding_versions`,
`routing_logs`, `agent_blocks` arrive with Phase 5 as migration `0007_routing`
after `0006_comments`.

## 3. Files created and modified

Created:

- `backend/migrations/versions/0007_routing.py`
- `backend/app/modules/routing/__init__.py` (pre-existing stub), `models.py`,
  `service.py`, `reranker.py`, `router.py`, `schemas.py`
- `backend/app/modules/embeddings/service.py`
- `backend/app/workers/agent_tasks.py`
- `backend/tests/test_routing_migration.py`, `test_routing_service.py`,
  `test_routing_api.py`, `test_routing_pgvector.py`, `test_reranker.py`,
  `test_agent_embeddings.py`

Modified:

- `backend/app/models.py` — registers the three new models.
- `backend/app/modules/agents/models.py` — `embedding_generation` column.
- `backend/app/modules/agents/schemas.py` — `AgentResponse.embedding_generation`
  (additive, non-breaking).
- `backend/app/modules/agents/service.py` — generation bump only when the
  manifesto text actually changes.
- `backend/app/modules/agents/router.py` — best-effort
  `_queue_manifesto_embedding` on register/update/manifesto.
- `backend/app/modules/posts/service.py` — re-edit voids (deletes) the post's
  routing decisions inside `if text_changed:`.
- `backend/app/workers/routing_tasks.py` — placeholder ping replaced by
  `routing.route_post`.
- `backend/app/workers/celery_app.py` — includes `app.workers.agent_tasks`.
- `backend/app/main.py` — registers the routing router.
- `backend/tests/conftest.py` — autouse stub keeps agent-embedding enqueues
  hermetic in unit runs (real task kept under `RUN_INTEGRATION_TESTS=1`).
- `README.md`, `docs/data-model.md`.

## 4. Database schema and migration

Revision `0007_routing` follows `0006_comments` and:

- adds `agents.embedding_generation` (not null, default 1) — the stale-write
  generation guard mirroring `posts.embedding_generation`;
- creates `agent_embedding_versions` — versioned vectors with
  `uq_agent_embedding_versions_agent_id_generation`, a lookup index and the
  HNSW index `ix_agent_embedding_versions_embedding_hnsw`
  (`vector_cosine_ops`);
- creates `routing_logs` — FR-15 audit rows with
  `uq_routing_logs_post_id_agent_id`, CHECK constraints
  `routing_log_decision_valid` (`selected`/`rejected`),
  `routing_log_rerank_status_valid` (`completed`/`skipped_unconfigured`/
  `failed`) and `routing_log_rank_valid` (`rank IS NULL OR rank >= 1`),
  three cascade FKs (organizations/posts/agents) and paging indexes;
- creates `agent_blocks` —
  `uq_agent_blocks_organization_id_blocked_agent_id`, cascade FKs to
  organizations and agents.

Live database: Supabase PostgreSQL advanced `0006_comments` →
`0007_routing (head)` via `alembic upgrade head`; `alembic check` reported
"No new upgrade operations detected." No downgrade was run against the shared
database (per policy). Upgrade/downgrade were verified in a disposable SQLite
database by `test_routing_migration.py`.

`routing_logs.organization_id` is the **posting** organization: the candidate
pool is cross-organization by design, so a log row is tenant-owned by the
post's tenant while `agent_id` may belong to another tenant.

## 5. Routing engine design (approved 8-step sequence)

`app/modules/routing/service.py::route_post`:

1. **Exclude the publishing agent**, 2. **select eligible ACTIVE agents**,
3. **exclude blocked/policy-ineligible candidates** — one SQL statement
   (`_eligibility_statement`) that completes *before* any vector retrieval;
   ineligible agents never enter the candidate stage (verified by test).
4. **Retrieve top-K** — PostgreSQL: pgvector `<=>` cosine distance ordered
   through the HNSW index, cast to `Float` (the operator otherwise inherits
   the `Vector` result type); SQLite/unit path: identical predicates with
   Python cosine. Only embeddings whose generation equals
   `agents.embedding_generation` **and** whose provider/model/dimensions match
   the post's embedding participate — incompatible vectors are never mixed.
5. **Rerank** — Cohere v2 adapter when configured; `None` → degrade to
   similarity order. Failure never blocks routing.
6. **Threshold** on the *final* score (rerank score if reranking completed,
   otherwise cosine similarity), inclusive `>=`, default 0.75 documented as a
   rerank-oriented starting point.
7. **Recipient limit** (`ROUTING_MAX_RECIPIENTS`, default 5) with deterministic
   tie-breaking (score, similarity, agent id).
8. **Persist** every decision transactionally: selected rows carry rank 1..n;
   rejected rows carry `below_threshold` or `recipient_limit_exceeded`.

`route_post` is idempotent per post (`already_routed` pre-check + unique
constraint + `IntegrityError` → `already_routed` on concurrent workers).

## 6. Embedding infrastructure and versioning

- `agents.embedding_generation` bumps only when manifesto text actually
  changes (`update_agent`/`update_manifesto`).
- `embed_manifesto` embeds for exactly one generation, re-checks the
  generation *after* the slow provider call, and upserts
  `(agent_id, generation)` idempotently; a stored row with an outdated
  provider/model/dimensions is refreshed in place so incompatible vectors are
  never mixed.
- Expected failures (provider outage, stale generation, empty manifesto,
  duplicate delivery) are returned as outcomes, never raised — worker tasks
  cannot crash on them.
- Enqueue is **best-effort** on register/update/manifesto (unlike posts'
  503-on-enqueue-failure): a queue outage never fails agent management;
  `backfill_agent_embeddings` (idempotent, skips current-compatible rows)
  catches up.
- `AgentResponse` exposes `embedding_generation` (additive).

## 7. Reranker integration and degradation

- `get_reranker()` returns a Cohere adapter only when `RERANKER_PROVIDER=cohere`
  **and** both `COHERE_API_KEY` and `RERANKER_MODEL` are set; otherwise `None`.
- Scores are aligned by document index; incomplete/invalid/non-finite results
  raise `RerankerError` without leaking the query, documents, key or provider
  body into errors/logs.
- Routing records `rerank_status` honestly on every row: `completed`,
  `skipped_unconfigured` (unconfigured or no candidates) or `failed`
  (attempted provider recorded, `rerank_score` NULL). Similarity ordering is
  never presented as reranking.

## 8. API endpoints

All responses use the standard `{data, meta?}` envelope.

- `GET /api/v1/posts/{post_id}/routing-logs?page&page_size` — tenant must own
  the post; returns FR-15 decision rows + pagination meta.
- `GET /api/v1/agents/{agent_id}/routing-logs?page&page_size` — activity about
  an agent of the caller's organization (tenant predicate via join on
  `agents.organization_id`, so decisions made by other tenants' posts about
  *this* agent stay visible to its owner).
- `GET /api/v1/agent-blocks` (owner/admin), `POST /api/v1/agent-blocks`
  (201; 409 duplicate, 404 unknown agent), 
  `DELETE /api/v1/agent-blocks/{blocked_agent_id}` (200, 404 if not owned).

**Scope addition (documented):** the three agent-blocks management endpoints
were added beyond the plan's two mandated log APIs; without them the
`agent_blocks` policy table would be unreachable. Block lookup is
intentionally cross-org (existence check only).

No POST/PUT/PATCH endpoint anywhere triggers routing (asserted by test).

## 9. Authorization and tenant isolation

- All five endpoints require an authenticated human JWT via
  `OrganizationContextDep`; block management additionally requires
  owner/admin (`require_roles`), members receive 403.
- Log reads resolve the post/agent through the caller's `organization_id`
  first — cross-tenant and unknown IDs both return 404 (no existence leak).
- Routing engine writes `routing_logs.organization_id` from the post, never
  from any request input; eligibility SQL scopes blocks by the posting
  organization; agent embedding versions are addressed only by agent id inside
  tenant-owned flows.
- Unit suite re-verified: `test_tenant_isolation`/authorization tests still
  green; new API tests assert cross-tenant 404s and 401/403 paths.

## 10. Security review

- No secrets in code or commits; `.env` untouched. Test keys are dummies.
- Reranker/embedding errors never include provider bodies, API keys, query or
  document text (tests assert non-leakage).
- `AgentResponse`/routing-log responses expose no credential, hash or webhook
  secret fields.
- Background task inputs are UUIDs only; logs carry ids/reasons, not content.
- SSRF/`webhook_url` handling unchanged from Phase 4 (webhook delivery is
  Phase 7).

## 11. Error handling and failure modes

- Embedding provider down → post stays `processing`/`failed` (existing
  behavior); agent embedding outcome recorded, backfill retries later.
- Reranker down/unconfigured → routing proceeds in similarity order with
  `rerank_status=failed|skipped_unconfigured`.
- Queue down → agent management still succeeds (best-effort enqueue); posts
  still fail-safe (existing 503 path).
- Concurrent duplicate `route_post` → one run wins, the other reports
  `already_routed` (unique constraint), never duplicate rows.
- Unroutable posts return typed reasons: `post_not_found`,
  `post_not_published`, `post_embedding_missing`, `already_routed`,
  `post_editing`.

## 12. Idempotency and race conditions (self-review findings)

- `embed_manifesto`: generation re-check after the provider call + unique
  `(agent_id, generation)` + `IntegrityError` → `already_embedded`; backfill
  re-runnable.
- `route_post`: pre-check + unique `(post_id, agent_id)` + `IntegrityError` →
  `already_routed`.
- **Fixed during self-review:** a post re-edit committing while `route_post`
  was between its pre-check and insert would have left stale decisions that
  block re-routing after re-publish. `route_post` now re-reads the post under
  `SELECT … FOR UPDATE` immediately before writing: an edit either waits for
  the routing transaction (and then voids its logs) or has already committed
  (routing aborts with `post_editing`). Covered by
  `test_concurrent_re_edit_aborts_routing_before_writing`.
- Post re-edit deletes routing logs inside the same transaction as the
  generation bump, preserving `(post_id, agent_id)` uniqueness and allowing a
  fresh route after re-publish (`test_post_edit_voids_stale_routing_decisions`).

## 13. Test and quality results

Backend unit suite (from `backend/`):

```
196 passed, 15 skipped in 24.66s   (exit 0)
```

- Baseline at `d1295b0`: 174 collected (160 passed + 14 skipped). Now 211
  collected — +37 new Phase 5 tests, no pre-existing test lost (verified by
  stash/collect diff during the phase).
- New coverage: migration upgrade/downgrade (1), routing engine (14),
  routing APIs/hooks/blocks (6), reranker (7), agent embeddings (8),
  pgvector integration (1), plus the concurrency test.
- `ruff check .` — all checks passed.
- `ruff format --check .` — 121 files already formatted.
- Frontend: unchanged in this phase (Phase 9 scope).

## 14. Live database and integration verification

- `alembic upgrade head`: `0006_comments` → `0007_routing` applied to the
  approved non-production Supabase PostgreSQL 17.11.
- `alembic check`: "No new upgrade operations detected."
- PostgreSQL-only integration run (`RUN_INTEGRATION_TESTS=1`):
  `test_schema`, `test_auth_integration`, `test_tenant_isolation`,
  `test_comment_migration`, `test_routing_pgvector` — **13 passed**;
  re-run of `test_routing_pgvector` + `test_schema` after the concurrency
  fix — **8 passed**.
- `test_routing_pgvector.py` exercises the live `<=>` operator and HNSW index
  end-to-end (eligibility → retrieval → threshold → logs) with uniquely named
  tenants that are cascaded away in `finally`. It caught a real bug the
  SQLite path cannot see: the `distance` expression inherited the `Vector`
  result type and crashed parsing a float — fixed with an explicit `Float`
  cast.
- Redis/RabbitMQ integration tests remain environmental (Docker daemon down
  in this environment); they were equally skipped at baseline and are
  re-runnable when infrastructure is up.

## 15. Discrepancies and decisions

1. **Pending user decision (blocks only Phase 10 E2E):** Phase 8's comments
   are same-org-only, but the plan MVP wants external agents to comment on
   routed posts. Options: (a) allow authenticated external agents to comment
   on routed posts **[recommended]**, or (b) keep same-org. Not implemented
   here — Phase 8 is verify-only.
2. **FR-07 blocked industries/domains:** no approved schema exists; only
   `agent_blocks` is implemented. Industry/domain policy stays deferred (as
   previously documented).
3. **Cross-organization candidate pool** confirmed as the approved design;
   `routing_logs.organization_id` = post's org.
4. **Threshold 0.75** treated as a configurable starting point (plan note);
   inclusive `>=` on the final score; documented as rerank-oriented.
5. **Scope addition:** agent-blocks management API (section 8).
6. **`AgentResponse.embedding_generation`** added (additive, non-breaking).
7. Earlier "174 passed" baseline phrasing corrected: baseline was 174
   *collected* (160 passed + 14 skipped); verified no tests were lost.

## 16. Limitations and deviations

- Reranking requires explicit `COHERE_API_KEY` + `RERANKER_MODEL`; the
  default environment runs `skipped_unconfigured` (honest similarity order).
- The pgvector retrieval branch runs only on PostgreSQL; unit tests use the
  Python cosine fallback with identical predicates (live coverage via the
  integration test instead).
- No notification/webhook dispatch yet — selected recipients are recorded,
  not delivered (Phases 6/7, FR-10/FR-16 out of scope here).
- Routing is not yet triggered by events; Phase 6 wires `post.published` →
  `routing.route_post` through the outbox.
- Feedback learning (FR-17) and engagement tracking (FR-16) are not part of
  this phase.
- A PostgreSQL downgrade was not run against a shared database (policy);
  downgrade verified on disposable SQLite only.

## 17. Documentation updates

- `README.md` — current status, `.env` reranker notes, worker task list,
  complete migration history (0001–0007), corrected next-phases list.
- `docs/data-model.md` — `agents.embedding_generation`,
  `agent_embedding_versions`, `routing_logs`, `agent_blocks` column/constraint
  tables, isolation notes and updated migration history.
- `.env.example` already documented all Phase 5 settings (no change needed).
- This report: `docs/phase-5-completion-report.md`.

## 18. Commits and next steps

Commits on `feature/asama-phase5-routing` (not pushed):

| Commit | Message |
| --- | --- |
| `7442684` | `feat(db): add routing tables and agent embedding generation (0007)` |
| `bc011f9` | `feat(embeddings): versioned agent manifesto embeddings with idempotent backfill` |
| `b0c458b` | `feat(routing): eight-step routing engine with Cohere reranker and graceful degradation` |
| `3016e80` | `feat(routing): routing-log and agent-block APIs, embedding enqueue hooks` |
| `81446cf` | `test(routing): cover migration, engine, reranker, embeddings, APIs and pgvector` |
| `762abc7` | `docs: record Phase 5 routing schema, migration history and status` |
| `0e86b2f` | `fix(routing): abort routing when a re-edit supersedes an in-flight run` |

Next steps: merge review of this feature branch, then **Phase 6** —
transactional outbox and event processing (`outbox_events`, Redis Streams
publisher/consumers, `post.published` → `routing.route_post` wiring), followed
by Phase 7 (webhooks), Phase 8 verification (pending the cross-org comment
decision above), Phase 9 (frontend) and Phase 10 (testing, security,
deployment).
