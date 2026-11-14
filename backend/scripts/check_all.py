"""Run every Sprint 1 infrastructure smoke check.

Run from the ``backend`` directory:

    python -m scripts.check_all
"""

from __future__ import annotations

from collections.abc import Callable

from scripts import smoke_db, smoke_rabbitmq, smoke_redis


def main() -> None:
    checks: list[tuple[str, Callable[[], dict[str, str]]]] = [
        ("PostgreSQL", smoke_db.check),
        ("Redis", smoke_redis.check),
        ("RabbitMQ", smoke_rabbitmq.check),
    ]

    failures = 0
    for name, check in checks:
        try:
            details = check()
            print(f"{name}: OK ({details})")
        except Exception as exc:  # noqa: BLE001 - report all checks, then fail
            failures += 1
            print(f"{name}: FAILED ({type(exc).__name__}: {exc})")

    if failures:
        raise SystemExit(1)

    print("All infrastructure checks passed.")


if __name__ == "__main__":
    main()
