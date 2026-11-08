"""Dependency that turns `Authorization: Bearer <token>` into the current user (US-21 AC4)."""

from typing import Annotated

from fastapi import Depends
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from app.auth.service import UnauthorizedError, user_for_token
from app.db.models import User
from app.db.session import get_db

# auto_error=False: a missing header goes through our own 401 format instead of FastAPI's 403.
# Declaring the scheme also adds the "Authorize" button to /docs.
bearer = HTTPBearer(auto_error=False, description="Token from POST /api/auth/login.")


def bearer_token(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer)],
) -> str:
    if credentials is None or not credentials.credentials:
        raise UnauthorizedError
    return credentials.credentials


def current_user(
    token: Annotated[str, Depends(bearer_token)], db: Annotated[Session, Depends(get_db)]
) -> User:
    return user_for_token(db, token)


CurrentUser = Annotated[User, Depends(current_user)]
BearerToken = Annotated[str, Depends(bearer_token)]
