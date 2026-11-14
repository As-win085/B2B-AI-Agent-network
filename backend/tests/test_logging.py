"""ASAMA-101: JSON logs carry the active request ID."""

from __future__ import annotations

import json
import logging

from app.core.context import get_request_id, reset_request_id, set_request_id
from app.core.logging import JsonFormatter


def _record(**extra: object) -> logging.LogRecord:
    record = logging.LogRecord(
        name="test",
        level=logging.INFO,
        pathname=__file__,
        lineno=1,
        msg="hello",
        args=(),
        exc_info=None,
    )
    for key, value in extra.items():
        setattr(record, key, value)
    return record


def test_formatter_reads_request_id_from_context() -> None:
    token = set_request_id("req-context-1")
    try:
        payload = json.loads(JsonFormatter().format(_record()))
    finally:
        reset_request_id(token)

    assert payload["request_id"] == "req-context-1"


def test_explicit_record_request_id_wins() -> None:
    token = set_request_id("req-context-2")
    try:
        payload = json.loads(JsonFormatter().format(_record(request_id="req-explicit")))
    finally:
        reset_request_id(token)

    assert payload["request_id"] == "req-explicit"


def test_no_request_id_outside_request() -> None:
    assert get_request_id() is None
    payload = json.loads(JsonFormatter().format(_record()))
    assert "request_id" not in payload
