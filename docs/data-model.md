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

`agents`, `agent_credentials` and every other table are intentionally deferred
to their feature phases, matching the approved database implementation order.

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
