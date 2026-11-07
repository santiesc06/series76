"""Shared test setup.

Tests never read .env (no secrets, no real LLM calls) and run against a dedicated PostgreSQL
database (TEST_DATABASE_URL), created and migrated once per test session.
"""

import json
import os

os.environ["APP_DISABLE_DOTENV"] = "1"  # must run before any `app` import reads settings

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session, sessionmaker

TEST_DATABASE_URL = os.environ.get(
    "TEST_DATABASE_URL", "postgresql+psycopg://series76:series76@localhost:5433/series76_test"
)
# In CI the database must exist; locally DB tests are skipped if Postgres is not running.
REQUIRE_DB = os.environ.get("REQUIRE_DB") == "1"


def _ensure_database(url: str) -> None:
    target = make_url(url)
    admin = create_engine(target.set(database="postgres"), isolation_level="AUTOCOMMIT")
    with admin.connect() as conn:
        exists = conn.execute(
            text("SELECT 1 FROM pg_database WHERE datname = :name"), {"name": target.database}
        ).scalar()
        if not exists:
            conn.execute(text(f'CREATE DATABASE "{target.database}"'))
    admin.dispose()


@pytest.fixture(scope="session")
def db_engine():
    try:
        _ensure_database(TEST_DATABASE_URL)
    except OperationalError as exc:
        if REQUIRE_DB:
            raise
        pytest.skip(f"PostgreSQL not reachable for tests ({exc.__class__.__name__})")

    from alembic.config import Config

    from alembic import command
    from ingest import paths
    from ingest.load import load_dataset

    config = Config(str(paths.REPO_ROOT / "backend" / "alembic.ini"))
    config.set_main_option("script_location", str(paths.REPO_ROOT / "backend" / "alembic"))
    config.set_main_option("sqlalchemy.url", TEST_DATABASE_URL)
    command.downgrade(config, "base")
    command.upgrade(config, "head")

    engine = create_engine(TEST_DATABASE_URL)
    dataset = json.loads(paths.PROCESSED.read_text(encoding="utf-8"))
    with Session(engine) as session:
        load_dataset(session, dataset)
        session.commit()
    yield engine
    engine.dispose()


@pytest.fixture
def db(db_engine):
    """A session whose changes are rolled back after each test."""
    connection = db_engine.connect()
    transaction = connection.begin()
    session = sessionmaker(bind=connection, join_transaction_mode="create_savepoint")()
    yield session
    session.close()
    transaction.rollback()
    connection.close()
