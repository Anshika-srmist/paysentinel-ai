"""
Database setup for PaySentinel AI.

The engine is driven by the ``DATABASE_URL`` environment variable:

* **unset**  -> ``sqlite:///./paysentinel.db`` — the zero-setup default for
  local development and the test suite (tests actually use their own
  in-memory SQLite, see ``tests/conftest.py``).
* **set**    -> whatever you point it at. Every deployed environment sets
  this to a Postgres URL.

Schema is owned by Alembic (``migrations/``), not this module — run
``alembic upgrade head`` to create or migrate it. Nothing here issues DDL.
"""
import os

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, declarative_base

_DEFAULT_SQLITE_URL = "sqlite:///./paysentinel.db"


def _normalise_url(raw: str) -> str:
    """
    Managed Postgres providers (Render, Heroku, some Neon copy-paste strings)
    hand out ``postgres://``; SQLAlchemy 2.x needs an explicit driver. Pin it
    to psycopg 3.
    """
    if raw.startswith("postgres://"):
        raw = "postgresql+psycopg://" + raw[len("postgres://"):]
    elif raw.startswith("postgresql://"):
        raw = "postgresql+psycopg://" + raw[len("postgresql://"):]
    return raw


DATABASE_URL = _normalise_url(os.getenv("DATABASE_URL", "").strip() or _DEFAULT_SQLITE_URL)
_IS_SQLITE = DATABASE_URL.startswith("sqlite")

if _IS_SQLITE:
    engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False})
else:
    engine = create_engine(
        DATABASE_URL,
        pool_pre_ping=True,      # drop connections killed by the DB / a proxy
        pool_size=5,
        max_overflow=10,
        pool_recycle=1800,
    )

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
