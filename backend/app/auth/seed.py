"""Pre-loaded test users (US-21 AC3, design U5): `python -m app.auth.seed`.

`seed_users.json` holds only emails, names and argon2id hashes; the passwords are test values
documented in the README. Idempotent: users are matched by email and updated, never duplicated.
Conversations are untouched.
"""

import json
import logging
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth.service import normalize_email
from app.db.models import User

SEED_FILE = Path(__file__).with_name("seed_users.json")
log = logging.getLogger("seed")


def seed_users(db: Session, path: Path = SEED_FILE) -> int:
    entries = json.loads(path.read_text(encoding="utf-8"))
    for entry in entries:
        email = normalize_email(entry["email"])
        user = db.scalar(select(User).where(User.email == email))
        if user is None:
            db.add(User(email=email, name=entry["name"], password_hash=entry["password_hash"]))
        else:
            user.name = entry["name"]
            user.password_hash = entry["password_hash"]
    db.commit()
    return len(entries)


def main() -> None:
    from app.db.session import SessionLocal

    with SessionLocal() as db:
        count = seed_users(db)
    print(f"test users: {count} seeded")


if __name__ == "__main__":
    main()
