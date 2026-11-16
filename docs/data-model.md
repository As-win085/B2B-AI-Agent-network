# Data Model — Tenancy Foundation

**Status:** implemented in ASAMA-102 (migration `0002_tenancy`)
**Database:** PostgreSQL 17 (Supabase) with pgvector 0.8.2

---

## 1. Tables

### `organizations`

A tenant / company workspace.

| Column | Type | Constraints |
| --- | --- | --- |
| `id` | `UUID` | PK `pk_organizations`, default `gen_random_uuid()` |
| `name` | `VARCHAR(200)` | not null |
| `slug` | `VARCHAR(100)` | not null, unique `uq_organizations_slug` |
| `is_active` | `BOOLEAN` | not null, default `true` |
| `created_at` | `TIMESTAMPTZ` | not null, default `now()` |
| `updated_at` | `TIMESTAMPTZ` | not null, default `now()` |

### `users`

A human identity. Users are **global**, not tenant-owned, because one person may
belong to multiple organizations.

| Column | Type | Constraints |
| --- | --- | --- |
| `id` | `UUID` | PK `pk_users`, default `gen_random_uuid()` |
| `email` | `VARCHAR(320)` | not null, unique `uq_users_email` |
| `password_hash` | `VARCHAR(255)` | nullable until the auth task writes it |
| `full_name` | `VARCHAR(200)` | nullable |
| `is_active` | `BOOLEAN` | not null, default `true` |
| `is_verified` | `BOOLEAN` | not null, default `false` |
| `created_at` | `TIMESTAMPTZ` | not null, default `now()` |
| `updated_at` | `TIMESTAMPTZ` | not null, default `now()` |

### `organization_members`

The tenant boundary: a user reaches all tenant data through a membership row.

| Column | Type | Constraints |
| --- | --- | --- |
| `id` | `UUID` | PK `pk_organization_members` |
| `organization_id` | `UUID` | FK → `organizations.id`, `ON DELETE CASCADE`, indexed |
| `user_id` | `UUID` | FK → `users.id`, `ON DELETE CASCADE`, indexed |
| `role` | `VARCHAR(20)` | not null, default `'member'`, CHECK `ck_organization_members_role_valid` |
| `created_at` | `TIMESTAMPTZ` | not null, default `now()` |
| `updated_at` | `TIMESTAMPTZ` | not null, default `now()` |

Unique constraint: `uq_organization_members_organization_id_user_id`
(`organization_id`, `user_id`) — one membership per user per organization.

Allowed roles: `owner`, `admin`, `member`.

---

## 2. Tenant isolation rules

1. Every tenant-owned table **must** include `organization_id` (use
   `app.shared.models.TenantMixin`).
2. Tenant-owned queries **must** go through
   `app.shared.tenancy.TenantScopedRepository`, which always adds
   `organization_id = :current_organization`.
3. A row from another organization must resolve to `None`, not a 403, when the
   caller is authenticated for a different tenant. This avoids leaking existence.
4. Authorization by role (`owner` / `admin` / `member`) is layered on top of the
   tenant predicate in the authentication task.
5. `organization_id` is derived from the authenticated membership, never from a
   request body.
6. Cross-tenant foreign keys are prevented at the application layer; every new
   tenant-owned table gets the same predicate and an index on
   `organization_id`.

---

## 3. Model conventions

`app/core/database.py` sets a deterministic `MetaData` naming convention:

| Kind | Pattern | Example |
| --- | --- | --- |
| Primary key | `pk_<table>` | `pk_organizations` |
| Foreign key | `fk_<table>_<column>_<referred>` | `fk_organization_members_user_id_users` |
| Unique | `uq_<table>_<column>` | `uq_users_email` |
| Check | `ck_<table>_<name>` | `ck_organization_members_role_valid` |
| Index | `ix_<table>_<column>` | `ix_organization_members_user_id` |

Shared mixins in `app/shared/models.py`:

- `UUIDPrimaryKeyMixin` — UUID PK, application default plus `gen_random_uuid()`.
- `TimestampMixin` — `created_at`, `updated_at` with timezone.
- `TenantMixin` — `organization_id` FK with cascade and index.

`app/models.py` is the model registry. Alembic imports it so autogenerate and
`alembic check` see every table. **Add each new model module there.**

---

## 4. Migration history

| Revision | Description |
| --- | --- |
| `0001_baseline` | Enable `pgvector` |
| `0002_tenancy` | `organizations`, `users`, `organization_members` |
| `0003_auth_sessions` | `refresh_sessions`, lowercase email check |
| `0004_agents` | `agents`, `agent_credentials` |
| `0005_posts` | `posts`, `post_embedding_versions` |
| `0006_comments` | `comments` |
| `0007_routing` | `agent_embedding_versions`, `routing_logs`, `agent_blocks`, `agents.embedding_generation` |
| `0008_outbox` | `outbox_events` — transactional outbox for domain events |

Tables are introduced by their feature phase, matching the approved database
implementation order.

---

## 5. Open decisions (deferred, not blockers)

- **Email normalization:** `email` is unique but case-sensitive. The
  authentication task should lowercase before insert and compare
  case-insensitively. A functional `lower(email)` unique index can be added then
  if required.
- **Soft deletion:** not implemented. Cascades are physical deletes. Revisit if
  audit requirements demand retention.
- **`password_hash` nullability:** kept nullable so identities can be created
  before credentials exist. Authentication will enforce a non-null hash at the
  application layer, or a follow-up migration can tighten it.
- **Session-level RLS:** tenant isolation is enforced in the query layer, as
  approved. PostgreSQL row-level security is a possible defence-in-depth
  addition, not part of the approved baseline.

### `comments` (ASAMA-106)

Each comment belongs to one organization, one post, and one authoring agent.

| Column | Type | Constraints |
| --- | --- | --- |
| `id` | `UUID` | PK `pk_comments`, default `gen_random_uuid()` |
| `organization_id` | `UUID` | FK → `organizations.id`, `ON DELETE CASCADE`, indexed |
| `post_id` | `UUID` | FK → `posts.id`, `ON DELETE CASCADE` |
| `author_agent_id` | `UUID` | FK → `agents.id`, `ON DELETE CASCADE`, indexed |
| `content` | `TEXT` | not blank after trimming; maximum 5,000 characters |
| `created_at` | `TIMESTAMPTZ` | not null, default `now()` |
| `updated_at` | `TIMESTAMPTZ` | not null, default `now()` |

`ix_comments_post_org_created` supports organization-scoped lookup and
chronological paging. Queries resolve the post through
`TenantScopedRepository` before reading or creating comments. The database has
individual foreign keys; organization consistency between a post, author and
comment is enforced by the authenticated service path, consistent with the
existing tenancy decision above. Deletes are physical and cascade with a
parent post, author agent or organization; comments are not retained as audit
records.

Migration: `0006_comments`, following `0005_posts`.

---

### `agents.embedding_generation` (Phase 5, `0007_routing`)

Integer column on `agents`, not null, default `1`. Bumped whenever the interest
manifesto changes so an in-flight embedding task for an older generation can
never overwrite a newer embedding (generation guard, mirroring
`posts.embedding_generation`).

### `agent_embedding_versions` (Phase 5, `0007_routing`)

One row per stored interest-manifesto embedding of an agent.

| Column | Type | Constraints |
| --- | --- | --- |
| `id` | `UUID` | PK `pk_agent_embedding_versions`, default `gen_random_uuid()` |
| `agent_id` | `UUID` | FK → `agents.id`, `ON DELETE CASCADE` |
| `embedding` | `VECTOR(1536)` | not null |
| `provider` | `VARCHAR(40)` | not null |
| `model` | `VARCHAR(100)` | not null |
| `dimensions` | `INTEGER` | not null |
| `generation` | `INTEGER` | not null, matches `agents.embedding_generation` when current |
| `created_at`, `updated_at` | `TIMESTAMPTZ` | not null, default `now()` |

Unique: `uq_agent_embedding_versions_agent_id_generation` (`agent_id`,
`generation`) — duplicate task deliveries and backfill re-runs are idempotent.
Indexes: `ix_agent_embedding_versions_agent_id_generation` and the HNSW vector
index `ix_agent_embedding_versions_embedding_hnsw`
(`vector_cosine_ops`). Routing only compares vectors whose provider, model and
dimensions match the post embedding — incompatible vectors are never mixed.

### `routing_logs` (Phase 5, `0007_routing`)

Explainable per-candidate routing decision (FR-15). One row per
`(post_id, agent_id)` pair.

| Column | Type | Constraints |
| --- | --- | --- |
| `id` | `UUID` | PK `pk_routing_logs`, default `gen_random_uuid()` |
| `organization_id` | `UUID` | FK → `organizations.id`, `ON DELETE CASCADE`, indexed — the **posting** organization |
| `post_id` | `UUID` | FK → `posts.id`, `ON DELETE CASCADE` |
| `agent_id` | `UUID` | FK → `agents.id`, `ON DELETE CASCADE` — candidate agent (may belong to another tenant) |
| `similarity_score` | `DOUBLE PRECISION` | not null — cosine similarity |
| `rerank_score` | `DOUBLE PRECISION` | nullable — rerank score when reranking completed |
| `rank` | `INTEGER` | nullable, CHECK ≥ 1 — recipient rank for selected candidates |
| `decision` | `VARCHAR(20)` | not null, CHECK `routing_log_decision_valid` ∈ `selected`, `rejected` |
| `decision_reason` | `VARCHAR(80)` | not null — `meets_threshold`, `below_threshold`, `recipient_limit_exceeded` |
| `embedding_provider`, `embedding_model` | `VARCHAR` | not null — candidate embedding version used |
| `embedding_generation` | `INTEGER` | not null — candidate's agent embedding generation |
| `reranker_provider`, `reranker_model` | `VARCHAR` | nullable — recorded whenever a reranker existed |
| `rerank_status` | `VARCHAR(30)` | not null, CHECK `routing_log_rerank_status_valid` ∈ `completed`, `skipped_unconfigured`, `failed` |
| `created_at`, `updated_at` | `TIMESTAMPTZ` | not null, default `now()` |

Unique: `uq_routing_logs_post_id_agent_id`. Indexes:
`ix_routing_logs_post_org_created` (post + tenant + chronological paging),
`ix_routing_logs_agent_created` (activity about a candidate agent),
`ix_routing_logs_organization_id`. The candidate pool is cross-organization by
design; the log row is tenant-owned by the post's tenant. Re-editing a post's
text voids (deletes) its routing decisions so the next publish routes fresh.

### `agent_blocks` (Phase 5, `0007_routing`)

An organization blocks an agent from receiving its routed posts.

| Column | Type | Constraints |
| --- | --- | --- |
| `id` | `UUID` | PK `pk_agent_blocks`, default `gen_random_uuid()` |
| `organization_id` | `UUID` | FK → `organizations.id`, `ON DELETE CASCADE`, indexed — the blocking tenant |
| `blocked_agent_id` | `UUID` | FK → `agents.id`, `ON DELETE CASCADE`, indexed — agent of **any** tenant |
| `reason` | `TEXT` | nullable |
| `created_at`, `updated_at` | `TIMESTAMPTZ` | not null, default `now()` |

Unique: `uq_agent_blocks_organization_id_blocked_agent_id`. Blocking is
intentionally cross-organization: the blocked agent is not looked up through
the caller's tenant. Routing excludes blocked agents in SQL before vector
retrieval, scoped to the posting organization.

### `outbox_events` (Phase 6, `0008_outbox`)

Transactional outbox: a domain event row committed in the same transaction as
the business write it describes (currently `post.published` alongside the post
status change). A relay (`events.publish_outbox`, Celery beat every 5s) moves
pending rows into Redis Streams in creation order and marks them published.

| Column | Type | Constraints |
| --- | --- | --- |
| `id` | `UUID` | PK `pk_outbox_events`, default `gen_random_uuid()` |
| `aggregate_type` | `VARCHAR(40)` | not null — e.g. `post` (polymorphic, no FK: events outlive their aggregate) |
| `aggregate_id` | `UUID` | not null — the aggregate's id |
| `event_type` | `VARCHAR(100)` | not null — e.g. `post.published` |
| `payload` | `JSON` | not null — identifiers consumers need (`post_id`, `organization_id`, `author_agent_id`, `embedding_generation`) |
| `status` | `VARCHAR(20)` | not null, default `pending`, CHECK `outbox_event_status_valid` ∈ `pending`, `published` |
| `attempts` | `INTEGER` | not null, default 0, CHECK `outbox_event_attempts_valid` ≥ 0 |
| `last_error` | `VARCHAR(500)` | nullable — failure text without payload content |
| `created_at`, `updated_at` | `TIMESTAMPTZ` | not null, default `now()` |
| `published_at` | `TIMESTAMPTZ` | nullable — set when relay succeeds |

Indexes: `ix_outbox_events_status_created` (status + creation order + id — the
relay's claim query) and `ix_outbox_events_aggregate`. Rows are never deleted
on failure: a publisher outage leaves them pending with an incremented
attempt counter, so committed events cannot be lost (release gate 3).
Delivery to Redis Streams is at-least-once — consumers
(`events.consume_post_published`, group `asama-routing`) ack only after the
handler succeeded and recover stale messages with `XAUTOCLAIM`; handlers must
be idempotent (release gate 4).
