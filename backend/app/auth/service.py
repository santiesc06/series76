"""Login logic (US-21, design U1-U2). Pure database work; the HTTP layer is in `app/api/auth.py`.

- Passwords: argon2id hashes only (`argon2-cffi` defaults). An unknown email is checked against a
  dummy hash, so both failures take the same time and look the same (US-21 AC1).
- Tokens: a random string is returned once; only its SHA-256 hash is stored, with an expiry.
  Logout deletes the row, so a token stops working at once (US-21 AC8).
"""

import hashlib
import secrets
from datetime import UTC, datetime, timedelta
from functools import lru_cache

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db.models import AuthToken, User

_hasher = PasswordHasher()


class UnauthorizedError(Exception):
    """Missing, invalid, expired or revoked token (401)."""


class InvalidCredentialsError(Exception):
    """Wrong email or password; deliberately the same error for both (401)."""


def hash_password(password: str) -> str:
    return _hasher.hash(password)


def verify_password(password_hash: str, password: str) -> bool:
    try:
        return _hasher.verify(password_hash, password)
    except (VerificationError, InvalidHashError):
        return False


@lru_cache
def _dummy_hash() -> str:
    return _hasher.hash(secrets.token_urlsafe(16))


def normalize_email(email: str) -> str:
    return email.strip().lower()


def _token_hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def _now() -> datetime:
    return datetime.now(UTC)


def authenticate(db: Session, email: str, password: str) -> User:
    user = db.scalar(select(User).where(User.email == normalize_email(email)))
    if user is None:
        verify_password(_dummy_hash(), password)  # same work as a real check
        raise InvalidCredentialsError
    if not verify_password(user.password_hash, password):
        raise InvalidCredentialsError
    if _hasher.check_needs_rehash(user.password_hash):
        user.password_hash = hash_password(password)
    return user


def issue_token(db: Session, user: User) -> tuple[str, datetime]:
    """A new token for `user`; also removes the user's expired tokens."""
    now = _now()
    db.execute(delete(AuthToken).where(AuthToken.user_id == user.id, AuthToken.expires_at <= now))
    token = secrets.token_urlsafe(32)
    expires_at = now + timedelta(hours=get_settings().auth_token_ttl_hours)
    db.add(AuthToken(token_hash=_token_hash(token), user_id=user.id, expires_at=expires_at))
    db.commit()
    return token, expires_at


def user_for_token(db: Session, token: str) -> User:
    row = db.get(AuthToken, _token_hash(token))
    if row is None or row.expires_at <= _now():
        raise UnauthorizedError
    return row.user


def revoke_token(db: Session, token: str) -> None:
    db.execute(delete(AuthToken).where(AuthToken.token_hash == _token_hash(token)))
    db.commit()
