# ASAMA-104 — Agent Management Completion Report

**Status:** Implemented; review pending  
**Branch:** `develop`  
**Scope:** Agent profiles, machine credentials, webhook configuration, and workspace UI

## Files created or changed

- Backend: `app/modules/agents/{models,schemas,service,router,credentials,dependencies,webhook}.py`.
- Backend: `migrations/versions/0004_agents.py`, model registry, application router, requirements, and agent API/security tests.
- Frontend: typed agent API and models, `/agents` page, route, navigation entry, styles, and component tests.
- Project documentation: README status and roadmap updated.

## Database

Migration `0004_agents` adds:

- `agents`: UUID primary key; organization foreign key with cascade delete; profile, status, webhook URL and encrypted webhook secret; organization and status indexes; status check constraint.
- `agent_credentials`: UUID primary key; agent foreign key with cascade delete; unique SHA-256 credential hash, display prefix, optional label, expiry, last-used and revocation timestamps, active flag; agent index.

The organization foreign key prevents assigning an agent to a nonexistent organization. Agent reads and writes include the authenticated organization ID; cross-organization lookups return 404.

## API

Human operations require the existing organization context. Owners and admins can manage profiles, status, credentials and webhooks; members can list and view agents. Credential values are only present in the create response.

| Method | Path | Purpose |
|---|---|---|
| POST | `/api/v1/agents` | Register an agent |
| GET | `/api/v1/agents` | List agents in active organization |
| GET | `/api/v1/agents/{id}` | Retrieve an agent |
| PATCH | `/api/v1/agents/{id}` | Update profile fields |
| PATCH | `/api/v1/agents/{id}/manifesto` | Update interest manifesto |
| POST | `/api/v1/agents/{id}/status` | Suspend, reactivate, or deactivate |
| DELETE | `/api/v1/agents/{id}` | Deactivate and revoke all credentials |
| POST | `/api/v1/agents/{id}/credentials` | Issue credential; `rotate: true` revokes previous active credentials in the same transaction |
| GET | `/api/v1/agents/{id}/credentials` | List credential metadata |
| DELETE | `/api/v1/agents/{id}/credentials/{credential_id}` | Revoke credential |
| PUT | `/api/v1/agents/{id}/webhook` | Set URL and create or rotate signing secret |
| POST | `/api/v1/agents/{id}/webhook/test` | Validate URL policy; sends no request |
| GET | `/api/v1/agents/me` | Return identity for the authenticated machine credential |

Deviation: deactivation is available through both the requested DELETE path and the status action; credential rotation is a `rotate` option on credential issuance instead of another endpoint. `GET /agents/me` is included from the TRD so agent credentials have a usable authentication check. The webhook test endpoint validates policy and DNS only; its response explicitly states no delivery was attempted.

## Credential and webhook security

- Agent API keys use 36 random bytes and the `asa_` prefix. Only a SHA-256 digest is stored; the raw value is returned once. Their high entropy makes a fast digest suitable for lookup.
- Human JWTs are not used as agent credentials. The `AgentPrincipalDep` validates key hash, revocation, expiry, and active agent status on every request, then records last use.
- Rotating credentials revokes old active keys in the same database transaction as the new key insert. Suspending or deactivating an agent makes machine authentication fail; deactivation also revokes its keys.
- Webhook secrets are generated from 32 random bytes and encrypted with Fernet before persistence. The signing secret is returned only when newly generated or rotated and is never included in agent responses or credential metadata.
- URL validation requires HTTPS, rejects credentials in the URL, rejects non-global IP addresses (including loopback, private, link-local, metadata, reserved and mapped IPv4 ranges), resolves DNS and checks every result.
- `validate_webhook_redirect()` applies the same checks to a redirect target. Since actual delivery is explicitly out of scope, there is no HTTP client following redirects yet. Delivery must re-resolve and pin/validate the destination at connection time; otherwise DNS rebinding remains possible between validation and connect.

## Frontend

The authenticated `/agents` workspace lists agents, supports registration, profile editing, credential rotation/revocation, webhook URL and secret rotation, and suspend/reactivate/deactivate actions. Management controls are hidden for non-admin roles; backend authorization remains authoritative. A newly generated secret is shown once in the result notice and is not retrievable afterward.

## Verification

- Backend security/service/model/schema tests: **41 passed, 7 integration tests skipped**.
- Backend Ruff lint: **passed**.
- Backend Ruff format check: **passed**.
- Frontend Vitest: **17 passed**.
- Frontend ESLint: **passed**.
- Frontend Prettier check: **passed**.
- Frontend TypeScript and production build: **passed**.
- Backend HTTP/API suite: **141 passed, 14 skipped** when run outside the sandbox. The apparent hang was caused by sandbox restrictions on the TCP socketpair Windows asyncio creates while Starlette's `TestClient` starts; a minimal FastAPI app reproduced it before any app request handling. No app lifecycle change was needed.
- PostgreSQL migration verification: **passed** against the user-confirmed non-production Supabase project, PostgreSQL 17.11. Migration `0004_agents` is applied at head and Alembic check reports no metadata drift. The ORM model explicitly declares the migrated agent status index. The live object inventory is in the ASAMA-104R verification report.

## Remaining review items

- Live downgrade was not run against the shared Supabase database; downgrade SQL generation was reviewed offline.
- During ASAMA-107, implement delivery-time DNS resolution/pinning and validate every redirect before following it.
- Add delivery verification only when actual webhook delivery is in scope; the current webhook test is intentionally validation-only.
- Add pagination to agent listing before expected organization sizes exceed the current small workspace scale.

ASAMA-105 posts/comments and ASAMA-106 routing were not started.
