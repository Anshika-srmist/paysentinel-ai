import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db.database import Base
from app.models.orm_models import PaymentEvent, RiskDecision
from app.seed import seed_if_empty


@pytest.fixture
def db():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(bind=engine)
    session = sessionmaker(bind=engine)()
    try:
        yield session
    finally:
        session.close()


def test_seed_populates_an_empty_database(db, monkeypatch):
    monkeypatch.setenv("PAYSENTINEL_SEED_ON_START", "1")
    made = seed_if_empty(db, count=30)
    ring_n = db.query(PaymentEvent).filter(PaymentEvent.device_id == "DEVICE_RING").count()
    assert ring_n >= 11                          # the coordinated ring landed
    assert made == 30 + ring_n                   # background + ring
    assert db.query(PaymentEvent).count() == made
    assert db.query(RiskDecision).count() == made


def test_seed_is_a_noop_when_data_exists(db, monkeypatch):
    monkeypatch.setenv("PAYSENTINEL_SEED_ON_START", "1")
    seed_if_empty(db, count=10)
    before = db.query(PaymentEvent).count()
    added = seed_if_empty(db, count=10)
    assert added == 0
    assert db.query(PaymentEvent).count() == before


def test_seed_respects_the_off_switch(db, monkeypatch):
    monkeypatch.setenv("PAYSENTINEL_SEED_ON_START", "0")
    assert seed_if_empty(db, count=10) == 0
    assert db.query(PaymentEvent).count() == 0


def test_seed_produces_a_spread_of_decisions(db, monkeypatch):
    monkeypatch.setenv("PAYSENTINEL_SEED_ON_START", "1")
    seed_if_empty(db, count=100)
    kinds = {d for (d,) in db.query(RiskDecision.decision).distinct()}
    # a realistic seed should exercise more than one decision path
    assert len(kinds) >= 3
    assert "APPROVE" in kinds
