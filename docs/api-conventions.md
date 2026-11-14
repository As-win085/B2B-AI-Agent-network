# API Conventions

**Status:** implemented in ASAMA-101
**Applies to:** every endpoint under `/api/v1`

The API returns exactly one of two body shapes. Do not add ad-hoc response
objects in feature modules.

---

## 1. Success envelope

Single resource:

```json
{
  "data": {
    "id": "6c1c0f1e-4b7a-4f5e-9f0e-2a7f2f5c9d11",
    "name": "Acme Robotics"
  }
}
```

Collection with pagination metadata:

```json
{
  "data": [],
  "meta": {
    "page": 1,
    "page_size": 20,
    "total": 42
  }
}
```

`meta` is optional and omitted when empty. `data` is always present on a
successful response.

Backend helper: `app.core.responses.success(data, meta=None)`.
OpenAPI type: `app.core.responses.ApiResponse[T]`.

---

## 2. Error envelope

Every error uses the same shape:

```json
{
  "error": {
    "code": "validation_error",
    "message": "Request validation failed.",
    "details": [
      {
        "field": "body.email",
        "message": "Field required",
        "type": "missing"
      }
    ],
    "request_id": "0f8fad5b-d9cb-469f-a165-70867728950e"
  }
}
```

| Field | Notes |
| --- | --- |
| `code` | Stable, machine-readable identifier. Never change an existing code's meaning. |
| `message` | Human-readable summary. Safe to display. |
| `details` | Optional field-level errors. Present for `validation_error`. |
| `request_id` | Same value as the `X-Request-ID` response header. |

### Error codes in use

| HTTP | `code` | Source |
| --- | --- | --- |
| 400 | `bad_request` | HTTP exception |
| 400 | `APP_ERROR` | Default `AppError` code; feature modules should override |
| 401 | `unauthorized` | HTTP exception (auth phase) |
| 403 | `forbidden` | HTTP exception (auth phase) |
| 404 | `not_found` | HTTP exception / unknown route |
| 405 | `method_not_allowed` | HTTP exception |
| 409 | `conflict` | HTTP exception (feature modules may use a domain code) |
| 422 | `validation_error` | FastAPI request validation |
| 429 | `rate_limited` | HTTP exception (future) |
| 500 | `internal_error` | Unhandled exception |

`AppError` subclasses or call sites may supply a domain-specific code, for
example `organization_exists`. Keep the HTTP status meaningful as well.

Domain errors are raised as:

```python
raise AppError(
    "Organization already exists.",
    code="organization_exists",
    status_code=409,
    details=[{"field": "slug"}],
)
```

---

## 3. Request correlation

`RequestContextMiddleware` assigns a request ID to every HTTP request.

- If the caller sends a safe `X-Request-ID` matching `^[A-Za-z0-9._:-]{1,128}$`,
  it is reused.
- Otherwise a UUID4 is generated.
- The value is echoed on the response as `X-Request-ID`.
- The value is attached to every structured JSON log record for that request.
- The value appears as `error.request_id` in error bodies.

Unsafe values (spaces, control characters, overlong input) are discarded and
replaced, which prevents log/header injection.

CORS exposes `X-Request-ID` so browser clients can read it.

### Trace flow

1. HTTP request receives a request ID.
2. API logs carry it.
3. Phase 6 domain events will carry the same ID through the outbox and workers
   (`event_id` is separate and represents the business event).

---

## 4. Exemptions

These endpoints intentionally keep a plain body because they are consumed by
infrastructure probes, not application clients:

| Endpoint | Body |
| --- | --- |
| `GET /health` | `HealthResponse` |
| `GET /health/ready` | `HealthResponse` |
| `GET /` | service metadata |

`GET /api/v1/health` and `GET /api/v1/health/ready` use the envelope.

---

## 5. Implementation notes

- Error handlers live in `app/main.py`.
- Payload helpers live in `app/core/responses.py`.
- Request ID storage lives in `app/core/context.py`.
- Middleware lives in `app/core/middleware.py`.
- Handlers must never return stack traces, SQL, connection strings, tokens or
  webhook secrets.

---

## 6. Frontend contract

`frontend/src/api/client.ts`:

- `apiRequest<T>(path, init)` unwraps `data` and throws `ApiError`.
- `ApiError` exposes `status`, `code`, `requestId` and `details`.
- Non-JSON error bodies fall back to `Request failed with status <code>`.
