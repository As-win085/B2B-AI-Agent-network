"""Verify PostgreSQL connectivity and pgvector availability.

Run from the ``backend`` directory:

    python -m scripts.smoke_db
"""

from __future__ import annotations

from sqlalchemy import text

from app.core.database import engine


def check() -> dict[str, str]:
    with engine.begin() as connection:
        server_version = connection.execute(text("SELECT version()")).scalar_one()
        connection.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
        vector_version = connection.execute(
            text("SELECT extversion FROM pg_extension WHERE extname = 'vector'")
        ).scalar_one_or_none()
        database_name = connection.execute(text("SELECT current_database()")).scalar_one()

    if not vector_version:
        raise RuntimeError("pgvector extension is not installed")

    return {
        "database": str(database_name),
        "server": str(server_version).split(",")[0],
        "pgvector": str(vector_version),
    }


def main() -> None:
    details = check()
    print("PostgreSQL: OK")
    print(f"  database : {details['database']}")
    print(f"  server   : {details['server']}")
    print(f"  pgvector : {details['pgvector']}")


if __name__ == "__main__":
    main()
