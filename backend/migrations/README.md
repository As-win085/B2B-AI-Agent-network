# Alembic migrations

Migrations are applied from the `backend/` directory:

```bash
alembic upgrade head
alembic downgrade -1
alembic current
```

`migrations/env.py` reads `DATABASE_URL` from the root `.env` file, so the API
and migrations always target the same database.

Sprint 1 contains only the baseline migration (`0001_baseline`), which enables
the pgvector extension. Feature tables are added phase by phase.
