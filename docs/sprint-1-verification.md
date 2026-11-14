# Sprint 1 — Verification Record

**Date:** 14 November 2026
**Environment:** local development on Windows
**Branch:** `develop`

## Infrastructure

| Check | Result |
| --- | --- |
| Supabase PostgreSQL connection | Passed |
| PostgreSQL server version | 17.11 |
| pgvector extension | 0.8.2 |
| Alembic baseline migration | `0001_baseline (head)` applied |
| Redis stream publish/read | Passed |
| RabbitMQ publish/consume | Passed |
| Docker Compose services | `redis`, `rabbitmq` healthy |

## API

| Endpoint | Result |
| --- | --- |
| `GET /health` | `200`, status `ok` |
| `GET /api/v1/health` | `200`, status `ok` |
| `GET /api/v1/health/ready` | `200`, postgres/redis/rabbitmq all `ok` |

## Backend quality gates

| Gate | Result |
| --- | --- |
| `ruff check .` | Passed |
| `ruff format --check .` | Passed |
| `pytest` (unit) | 7 passed, 3 integration skipped |
| `pytest` with `RUN_INTEGRATION_TESTS=1` | 10 passed |

## Frontend quality gates

| Gate | Result |
| --- | --- |
| `npm run lint` | Passed |
| `npm run format:check` | Passed |
| `npm run test` | 4 passed |
| `npm run build` | Passed |

## Dependency audit

- Production dependencies (`npm audit --omit=dev`): **0 vulnerabilities**.
- Development-only advisories remain in `vitest`/`tinypool` and
  `typescript-eslint`/`minimatch`. They are not shipped in the production bundle and
  should be upgraded during the Phase 10 security review.

## Security notes

- The Supabase password is stored only in the git-ignored root `.env`.
- `.env`, virtual environments, `node_modules` and build output are excluded by
  `.gitignore`.
- No credentials, tokens or connection strings are logged by the API.
- The Supabase credential was shared outside the secret store during setup; rotate it in
  the Supabase dashboard and update `.env` before any shared or production use.
