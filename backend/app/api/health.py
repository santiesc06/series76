"""Liveness and readiness probes."""

from typing import Annotated

from fastapi import APIRouter, Depends, Response, status
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.db.session import get_db

router = APIRouter(tags=["health"])


@router.get("/health")
def liveness() -> dict[str, str]:
    """The process is up. Does not touch the database."""
    return {"status": "ok"}


@router.get("/health/ready")
def readiness(response: Response, db: Annotated[Session, Depends(get_db)]) -> dict[str, str]:
    """The API can serve requests: the database is reachable."""
    try:
        db.execute(text("SELECT 1"))
    except SQLAlchemyError:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
        return {"status": "unavailable", "database": "down"}
    return {"status": "ok", "database": "up"}
