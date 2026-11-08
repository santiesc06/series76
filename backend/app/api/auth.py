"""Login endpoints (US-21, design U4). Every other `/api/*` route needs the token they issue."""

from typing import Annotated

from fastapi import APIRouter, Depends, Response
from sqlalchemy.orm import Session

from app.api.schemas import ErrorResponse, LoginRequest, LoginResponse, UserOut
from app.auth import service
from app.auth.deps import BearerToken, CurrentUser
from app.db.session import get_db

router = APIRouter(prefix="/api/auth", tags=["auth"])
DB = Annotated[Session, Depends(get_db)]
UNAUTHORIZED = {401: {"model": ErrorResponse}}


@router.post("/login", response_model=LoginResponse, responses=UNAUTHORIZED)
def login(body: LoginRequest, db: DB) -> dict:
    """Email and password -> token. Wrong email and wrong password give the same error."""
    user = service.authenticate(db, body.email, body.password)
    token, expires_at = service.issue_token(db, user)
    return {"token": token, "expires_at": expires_at, "user": user}


@router.post("/logout", status_code=204, responses=UNAUTHORIZED)
def logout(token: BearerToken, user: CurrentUser, db: DB) -> Response:
    """Revokes the token sent with this request."""
    service.revoke_token(db, token)
    return Response(status_code=204)


@router.get("/me", response_model=UserOut, responses=UNAUTHORIZED)
def me(user: CurrentUser) -> UserOut:
    """The user the token belongs to (the app checks a saved token with it)."""
    return UserOut.model_validate(user, from_attributes=True)
