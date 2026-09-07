"""
Shared test fixtures.

Every API test runs against an isolated in-memory SQLite database rather
than the real `paysentinel.db` file, so the suite is order-independent and
re-runnable (previously `test_api.py` collided with its own rows on a
second run). The `get_db` dependency is overridden for the whole session.
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.cache import cache_clear, limiter
from app.db.database import Base, get_db
from app.main import app


@pytest.fixture(scope="session")
def _engine():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,   # one shared connection => in-memory DB persists
    )
    Base.metadata.create_all(bind=engine)
    yield engine
    engine.dispose()


@pytest.fixture(autouse=True)
def _isolated_db(_engine):
    """Point the app at the in-memory DB for the duration of each test module."""
    TestingSessionLocal = sessionmaker(bind=_engine, autoflush=False, autocommit=False)

    def _override_get_db():
        db = TestingSessionLocal()
        try:
            yield db
        finally:
            db.close()

    cache_clear()    # the 15s response cache must not leak state between tests
    limiter.reset()  # nor the in-memory rate-limit counters
    app.dependency_overrides[get_db] = _override_get_db
    yield
    app.dependency_overrides.pop(get_db, None)
