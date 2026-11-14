# Infrastructure

Local development infrastructure for Asama.ai.

## Services

`docker-compose.yml` (repository root) defines:

| Service | Purpose | Default port |
| --- | --- | --- |
| `redis` | Redis Streams domain events | 6379 |
| `rabbitmq` | Celery task broker + management UI | 5672 / 15672 |
| `postgres` | Optional local PostgreSQL + pgvector (profile `local-db`) | 5433 |

The default database is Supabase PostgreSQL, configured through `DATABASE_URL` in the
root `.env`.

## Commands

```powershell
docker compose up -d                 # Redis + RabbitMQ
docker compose ps                    # health status
docker compose logs -f rabbitmq      # follow logs
docker compose --profile local-db up -d
docker compose down                  # stop (keeps volumes)
docker compose down -v               # stop and delete volumes
```

## Smoke checks

From `backend/` with the virtual environment active:

```powershell
python -m scripts.check_all
```
