"""Reusable FastAPI dependency aliases.

Using ``Annotated`` keeps dependency injection out of parameter defaults, so
lint rules that flag function calls in defaults stay meaningful.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import Depends
from sqlalchemy.orm import Session

from app.core.database import get_db

DbSession = Annotated[Session, Depends(get_db)]
