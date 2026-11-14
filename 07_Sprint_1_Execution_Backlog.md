# Asama.ai — Sprint 1 Execution Backlog

**Sprint:** 1 — Project Foundation and Development Environment
**Maps to:** Phase 1 (Week 1)
**Status:** Ready for execution
**Date:** 14 November 2026

> **Sprint goal:** A developer can clone the repository, configure environment variables, start the full local stack (FastAPI, React, PostgreSQL + pgvector, Redis, RabbitMQ) and reach a working health-check endpoint.

---

## 1. Sprint Scope

**In scope (Phase 1):**

- Repository, branch strategy and monorepo structure.
- Backend FastAPI scaffold.
- Frontend React + TypeScript scaffold.
- Docker Compose for local infrastructure.
- PostgreSQL + pgvector, Redis and RabbitMQ.
- Environment variables and secrets baseline.
- Linting, formatting and initial test frameworks.
- Local development and test configuration.
- Setup documentation.

**Out of scope (later phases):**

- Organization/user database models and migrations beyond the Alembic bootstrap (Phase 2).
- Authentication and JWT (Phase 3).
- Agent registration and management (Phase 4).
- Embeddings, routing, outbox, webhooks, comments (Phases 5–8).
- Frontend feature screens (Phase 9).
- CI/CD and production deployment (Phase 10).

---

## 2. Issue Inventory

| ID | Title | Priority | Estimate | Depends on |
| --- | --- | --- | ---: | --- |
| ASAMA-001 | Create GitHub repository and branch strategy | P0 | 2 | — |
| ASAMA-002 | Create monorepo folder structure and `.gitignore` | P0 | 2 | 001 |
| ASAMA-003 | Configure environment variables and secrets baseline | P0 | 3 | 002 |
| ASAMA-004 | Initialize FastAPI backend with health endpoint | P0 | 3 | 002, 003 |
| ASAMA-005 | Initialize React + TypeScript frontend | P0 | 3 | 002, 003 |
| ASAMA-006 | Configure Docker Compose for local infrastructure | P0 | 5 | 002, 003 |
| ASAMA-007 | Configure PostgreSQL with pgvector | P0 | 3 | 006 |
| ASAMA-008 | Configure Redis and verify stream publish | P0 | 2 | 006 |
| ASAMA-009 | Configure RabbitMQ and verify task publish/consume | P0 | 2 | 006 |
| ASAMA-010 | Set up backend linting, formatting and test framework | P0 | 3 | 004 |
| ASAMA-011 | Set up frontend linting, formatting and test framework | P0 | 2 | 005 |
| ASAMA-012 | Bootstrap SQLAlchemy and Alembic | P0 | 3 | 007, 010 |
| ASAMA-013 | Write developer setup documentation | P1 | 3 | 004–012 |

**Total:** 13 issues, ~36 points.

> ASAMA-012 is pulled forward from Phase 2 to satisfy the approved example backlog ("Configure Alembic — initial migration runs successfully"). Only the bootstrap migration is required in Sprint 1.

---

## 3. Dependency Graph

```
ASAMA-001 Repository
        |
        v
ASAMA-002 Monorepo structure
        |
        +---------------------+---------------------+
        |                     |                     |
        v                     v                     v
ASAMA-003 Env config   ASAMA-004 FastAPI     ASAMA-005 React + TS
        |                     |                     |
        |                     v                     v
        |              ASAMA-010 BE tooling     ASAMA-011 FE tooling
        |                     |
        v                     v
ASAMA-006 Docker Compose -> ASAMA-012 Alembic
        |
        +---------+-----------+
        |         |           |
        v         v           v
   ASAMA-007  ASAMA-008   ASAMA-009
   Postgres    Redis       RabbitMQ
        |         |           |
        +---------+-----------+
                  |
                  v
          ASAMA-013 Setup docs
```

---

## 4. Issue Details

### ASAMA-001 — Create GitHub repository and branch strategy

**Priority:** P0 · **Estimate:** 2 · **Labels:** `infrastructure`, `documentation`

**Description:** Create the GitHub repository and define how work branches, merges and releases.

**Acceptance criteria:**

- [ ] Repository exists with an initial `main` branch.
- [ ] `develop` or agreed integration branch is defined.
- [ ] Branch naming convention documented (e.g. `feature/<id>-<slug>`, `fix/<slug>`, `chore/<slug>`).
- [ ] Pull-request and merge policy documented.
- [ ] Commit message convention documented (e.g. Conventional Commits).
- [ ] `main` is protected (no direct pushes) once the team/process requires it.

**Test requirements:** Not applicable — process/configuration issue.

---

### ASAMA-002 — Create monorepo folder structure and `.gitignore`

**Priority:** P0 · **Estimate:** 2 · **Labels:** `infrastructure`

**Description:** Create the approved folder layout so later features land in the correct place.

**Acceptance criteria:**

- [ ] `backend/`, `frontend/`, `infrastructure/`, `docs/` directories exist.
- [ ] Backend `app/` structure matches the approved plan (`core/`, `modules/`, `events/`, `workers/`, `shared/`).
- [ ] Frontend `src/` structure matches the approved plan (`api/`, `components/`, `features/`, `layouts/`, `pages/`, `routes/`, `hooks/`, `types/`, `utils/`).
- [ ] `.gitignore` covers Python, Node, environment files, build output and editor files.
- [ ] Placeholder `.gitkeep` or README files ensure empty directories are tracked.
- [ ] `.env` files are ignored; `.env.example` is tracked.
- [ ] Structure is committed.

**Test requirements:** `git status` shows no unintended files; `.env` is not tracked.

**Dependencies:** ASAMA-001

---

### ASAMA-003 — Configure environment variables and secrets baseline

**Priority:** P0 · **Estimate:** 3 · **Labels:** `backend`, `security`, `infrastructure`

**Description:** Define configuration management so no secret is committed to source control.

**Acceptance criteria:**

- [ ] `.env.example` documents every required variable with safe placeholder values.
- [ ] Backend loads configuration from environment variables.
- [ ] Configuration is validated at startup and fails fast on missing required values.
- [ ] Secrets are not logged and not returned by any endpoint.
- [ ] Local development uses `.env`; production expectations are documented.
- [ ] Database, Redis, RabbitMQ, JWT and embedding-provider placeholders are defined.

**Test requirements:** Unit test that missing required configuration raises a clear startup error; test that config values are not included in logs.

**Dependencies:** ASAMA-002

---

### ASAMA-004 — Initialize FastAPI backend with health endpoint

**Priority:** P0 · **Estimate:** 3 · **Labels:** `backend`

**Description:** Scaffold the FastAPI application using the approved modular structure.

**Acceptance criteria:**

- [ ] FastAPI app starts locally.
- [ ] `GET /health` (or `/api/v1/health`) returns `200` with service status and version.
- [ ] Readiness endpoint distinguishes "process up" from "dependencies reachable" where practical.
- [ ] Router registration pattern is established under `/api/v1`.
- [ ] Structured logging baseline is configured.
- [ ] Application runs through a documented command.

**Test requirements:** API test asserting the health endpoint returns `200` and the expected body.

**Dependencies:** ASAMA-002, ASAMA-003

---

### ASAMA-005 — Initialize React + TypeScript frontend

**Priority:** P0 · **Estimate:** 3 · **Labels:** `frontend`

**Description:** Scaffold the React + TypeScript application with routing and base layout.

**Acceptance criteria:**

- [ ] Vite (or agreed tooling) React + TypeScript project starts locally.
- [ ] React Router is configured with placeholder routes.
- [ ] Base app shell/layout renders.
- [ ] Environment variable handling for the API base URL is configured.
- [ ] Frontend can render a simple status page or call the backend health endpoint.
- [ ] Build command succeeds.

**Test requirements:** Component smoke test; production build succeeds.

**Dependencies:** ASAMA-002, ASAMA-003

---

### ASAMA-006 — Configure Docker Compose for local infrastructure

**Priority:** P0 · **Estimate:** 5 · **Labels:** `infrastructure`

**Description:** Provide one-command local infrastructure for PostgreSQL, Redis and RabbitMQ.

**Acceptance criteria:**

- [ ] `docker-compose.yml` defines PostgreSQL, Redis and RabbitMQ services.
- [ ] Named volumes persist data across restarts.
- [ ] Health checks are configured for each service.
- [ ] Ports and credentials come from environment variables.
- [ ] `docker compose up -d` starts all services successfully.
- [ ] `docker compose down` stops them cleanly.
- [ ] Startup order and dependency expectations are documented.

**Test requirements:** Manual verification that all containers report healthy; compose config validates.

**Dependencies:** ASAMA-002, ASAMA-003

---

### ASAMA-007 — Configure PostgreSQL with pgvector

**Priority:** P0 · **Estimate:** 3 · **Labels:** `database`, `infrastructure`

**Description:** Ensure the database runs with the pgvector extension available.

**Acceptance criteria:**

- [ ] PostgreSQL container uses a pgvector-enabled image or installs the extension.
- [ ] `CREATE EXTENSION IF NOT EXISTS vector;` succeeds.
- [ ] Backend can connect using configured credentials.
- [ ] A simple connectivity check or smoke test passes.
- [ ] Database port is not publicly exposed beyond local development needs.
- [ ] Data volume persists across container restarts.

**Test requirements:** Integration test or startup check that `SELECT extversion FROM pg_extension WHERE extname = 'vector';` returns a version.

**Dependencies:** ASAMA-006

---

### ASAMA-008 — Configure Redis and verify stream publish

**Priority:** P0 · **Estimate:** 2 · **Labels:** `infrastructure`, `backend`

**Description:** Make Redis available for domain events in later phases.

**Acceptance criteria:**

- [ ] Redis service is reachable from the backend.
- [ ] Connection settings come from environment variables.
- [ ] A smoke test publishes and reads a test stream entry (e.g. `XADD`/`XRANGE`).
- [ ] Redis persistence and restart behaviour are documented.

**Test requirements:** Integration test publishing a test event to a stream and reading it back.

**Dependencies:** ASAMA-006

---

### ASAMA-009 — Configure RabbitMQ and verify task publish/consume

**Priority:** P0 · **Estimate:** 2 · **Labels:** `infrastructure`, `backend`

**Description:** Make RabbitMQ available as the Celery task broker for later phases.

**Acceptance criteria:**

- [ ] RabbitMQ service is reachable from the backend.
- [ ] Management UI is available locally (if enabled).
- [ ] Connection settings come from environment variables.
- [ ] A smoke test publishes and consumes a test task/message.
- [ ] Queue durability expectations are documented.

**Test requirements:** Integration test publishing and consuming a test message.

**Dependencies:** ASAMA-006

---

### ASAMA-010 — Set up backend linting, formatting and test framework

**Priority:** P0 · **Estimate:** 3 · **Labels:** `backend`, `testing`

**Description:** Establish consistent code quality and a runnable test suite for the backend.

**Acceptance criteria:**

- [ ] Linter and formatter configured (e.g. Ruff, Black, mypy or equivalents).
- [ ] `pytest` configured with a `tests/` layout.
- [ ] Test database strategy documented (separate test database/schema).
- [ ] `lint`, `format-check` and `test` commands are documented and runnable.
- [ ] CI-ready commands exist (execution in CI is Phase 10).
- [ ] Initial health-endpoint test passes.

**Test requirements:** The configured test command runs the suite and returns success.

**Dependencies:** ASAMA-004

---

### ASAMA-011 — Set up frontend linting, formatting and test framework

**Priority:** P0 · **Estimate:** 2 · **Labels:** `frontend`, `testing`

**Description:** Establish consistent code quality and a runnable test suite for the frontend.

**Acceptance criteria:**

- [ ] ESLint and Prettier configured.
- [ ] Vitest + React Testing Library configured.
- [ ] `lint`, `format-check`, `test` and `build` commands are documented and runnable.
- [ ] Initial smoke test passes.
- [ ] TypeScript strict mode enabled.

**Test requirements:** The configured test command runs and the build succeeds.

**Dependencies:** ASAMA-005

---

### ASAMA-012 — Bootstrap SQLAlchemy and Alembic

**Priority:** P0 · **Estimate:** 3 · **Labels:** `backend`, `database`

**Description:** Establish the database access and migration tooling; full tenant tables are Phase 2.

**Acceptance criteria:**

- [ ] SQLAlchemy engine/session management is configured from environment variables.
- [ ] Alembic is initialized with the migrations directory.
- [ ] An initial empty (or baseline) migration applies successfully.
- [ ] `alembic upgrade head` and `alembic downgrade` work against the local database.
- [ ] Migration workflow is documented.
- [ ] No tenant or feature tables are created beyond what Phase 2 requires.

**Test requirements:** Run migrations from a clean database and verify the schema version; verify downgrade works.

**Dependencies:** ASAMA-007, ASAMA-010

---

### ASAMA-013 — Write developer setup documentation

**Priority:** P1 · **Estimate:** 3 · **Labels:** `documentation`

**Description:** Enable another developer to reproduce the environment from scratch.

**Acceptance criteria:**

- [ ] README covers prerequisites, clone, environment setup and start commands.
- [ ] Docker Compose usage is documented.
- [ ] Backend and frontend run commands are documented.
- [ ] Test, lint and format commands are documented.
- [ ] Alembic migration commands are documented.
- [ ] Health-check verification steps are documented.
- [ ] Common troubleshooting notes are included.

**Test requirements:** A second developer (or clean clone) follows the documentation and reaches the health endpoint successfully.

**Dependencies:** ASAMA-004 through ASAMA-012

---

## 5. Suggested Implementation Order

1. ASAMA-001 — Repository and branch strategy
2. ASAMA-002 — Monorepo structure
3. ASAMA-003 — Environment configuration
4. ASAMA-006 — Docker Compose
5. ASAMA-007 — PostgreSQL + pgvector
6. ASAMA-008 — Redis
7. ASAMA-009 — RabbitMQ
8. ASAMA-004 — FastAPI scaffold
9. ASAMA-005 — React + TypeScript scaffold
10. ASAMA-010 — Backend tooling
11. ASAMA-011 — Frontend tooling
12. ASAMA-012 — SQLAlchemy + Alembic bootstrap
13. ASAMA-013 — Setup documentation

> Steps 4–7 and 8–9 can proceed in parallel once ASAMA-002 and ASAMA-003 are complete.

---

## 6. Sprint 1 Definition of Done

A task is **Done** only when:

- [ ] Code is committed on a feature branch and merged through a pull request.
- [ ] Acceptance criteria are all satisfied.
- [ ] Linting and formatting pass.
- [ ] Required tests are added and pass.
- [ ] Documentation is updated where behaviour or setup changed.
- [ ] No secrets, credentials or tokens are committed or logged.
- [ ] The change is reproducible from a clean environment.

---

## 7. Sprint 1 Exit Criteria

The sprint is complete when:

1. A fresh clone can be configured from `.env.example`.
2. `docker compose up -d` starts PostgreSQL + pgvector, Redis and RabbitMQ.
3. Backend starts and `GET /health` returns `200`.
4. Frontend starts and renders the base application.
5. Backend and frontend lint, format-check, test and build commands pass.
6. `alembic upgrade head` applies the baseline migration successfully.
7. Redis and RabbitMQ smoke tests pass.
8. Setup documentation allows another developer to reproduce the environment.

---

## 8. Risks and Notes

| Risk | Mitigation |
| --- | --- |
| pgvector image/tag mismatch | Pin an explicit pgvector-enabled PostgreSQL image version |
| Local port conflicts | Make host ports configurable via environment variables |
| Docker resource pressure | Document minimum memory/CPU expectations |
| Alembic pulled forward from Phase 2 | Limit Sprint 1 to bootstrap/baseline only |
| Secrets leaking into git | `.gitignore` `.env`, review diffs, never log configuration values |

**Follow-on sprint:** Sprint 2 maps to Phase 2 — database foundation and multi-tenancy (`organizations`, `users`, `organization_members`, tenant isolation, initial indexes).
