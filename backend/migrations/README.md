# Alembic migrations

Migrations are applied from the `backend/` directory:

```bash
alembic upgrade head
alembic downgrade -1
alembic current
```

`migrations/env.py` reads `DATABASE_URL` from the root `.env` file, so the API
and migrations always target the same database.

Sprint 1 contains the baseline migration (`0001_baseline`), which enables the
pgvector extension.

`0002_tenancy` adds `organizations`, `users` and `organization_members`.

Always verify model/migration parity after a schema change:

```bash
alembic check
```

`migrations/env.py` imports `app.models`, which registers every ORM model on
`Base.metadata`. A new model module that is not imported there will be invisible
to autogenerate.

