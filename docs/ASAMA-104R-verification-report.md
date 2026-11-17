# ASAMA-104R — Final Verification Report

**Status:** Verification complete.  
**Branch:** `develop`  
**Scope:** Verification only. No ASAMA-105+ work was started.

## Backend API test hang

The earlier hang was caused by the sandbox, not application lifespan or service setup. A minimal FastAPI app with a trivial route hung before request dispatch. A `faulthandler` traceback showed Starlette `TestClient` starting AnyIO's blocking portal, where Windows asyncio attempted to create its self-pipe using `socket._fallback_socketpair()` and blocked in `socket.accept()`.

Running tests outside the sandbox resolved the issue. No application or fixture changes were required, and tests were not skipped or weakened.

## Test results

- Full backend suite outside the sandbox: **141 passed, 14 skipped**.
- Agent API tests: **26 passed**.
- Backend Ruff check and format check: passed.
- Frontend Vitest: **17 passed**.
- Frontend ESLint and Prettier check: passed.
- TypeScript and production build: passed.
- The 14 skipped tests are integration tests requiring live PostgreSQL, Redis and RabbitMQ; live infrastructure tests were not part of this database migration verification.

## Database identity and connection

The user confirmed that the configured Supabase project is an approved non-production project. The connection uses the Supabase regional pooler at `aws-0-ap-northeast-1.pooler.supabase.com:5432`, database `postgres`, a project-scoped pooler login, and `sslmode=require`. The URL credential encoding was validated without printing the password; authentication succeeded. Client connection metadata reported TLS active. The pooler maps the project-scoped login to the PostgreSQL role `postgres`.

The server reports PostgreSQL **17.11** and app environment `local`.

## Migration commands and results

- `alembic current` before upgrade: **`0003_auth_sessions`**.
- `alembic upgrade head`: **passed**, applying `0003_auth_sessions` → `0004_agents`.
- `alembic current` after upgrade: **`0004_agents (head)`**.
- First `alembic check` found `ix_agents_status` in the migration but not in ORM metadata. The model now declares this existing index.
- Rerun `alembic check`: **passed — no new upgrade operations detected**.

## Live object inspection

The database contains both expected tables and their expected fields:

- `agents`: UUID ID, non-null `organization_id`, company/industry/manifesto profile, status, webhook URL, encrypted webhook secret, and timestamps.
- `agent_credentials`: UUID ID, non-null `agent_id`, label, display prefix, credential hash, expiration, last-use, revocation, active flag, and timestamps.
- Constraints: both primary keys; cascading `agents.organization_id` → `organizations.id` FK; cascading `agent_credentials.agent_id` → `agents.id` FK; allowed-status check; unique credential-hash constraint.
- Supporting indexes: `ix_agents_organization_id`, `ix_agents_status`, and `ix_agent_credentials_agent_id`, plus primary-key and credential-hash unique indexes.
- Tenant ownership is stored on `agents.organization_id`; credentials inherit it through their agent relationship.

No downgrade was run against the shared Supabase database. The downgrade SQL was reviewed offline; a live downgrade was not needed for acceptance.

## Remaining warnings

No migration verification blocker remains. ASAMA-104R is complete. No ASAMA-105 or later work was started.
