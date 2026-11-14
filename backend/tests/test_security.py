from __future__ import annotations

from app.core.security import constant_time_compare


def test_constant_time_compare_equal() -> None:
    assert constant_time_compare("sha256=abc", "sha256=abc")


def test_constant_time_compare_different() -> None:
    assert not constant_time_compare("sha256=abc", "sha256=def")
