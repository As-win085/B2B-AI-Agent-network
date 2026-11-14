"""Application-wide exceptions and error helpers.

Sprint 1 only establishes the shape. Authentication, authorization and
domain-specific errors are added in later phases.
"""

from __future__ import annotations


class AppError(Exception):
    """Base class for expected, user-facing application errors."""

    def __init__(self, message: str, *, code: str = "APP_ERROR", status_code: int = 400):
        super().__init__(message)
        self.message = message
        self.code = code
        self.status_code = status_code
