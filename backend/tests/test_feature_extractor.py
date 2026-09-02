import os
import sys
from datetime import datetime

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db.database import Base
from app.engine.feature_extractor import extract_features
from app.models.orm_models import PaymentEvent


@pytest.fixture
def db():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    session = sessionmaker(bind=engine)()
    try:
        yield session
    finally:
        session.close()


def _add(db, **overrides):
    defaults = dict(
        transaction_id=f"TXN_{overrides.get('n', 0):04d}",
        customer_id="CUST_1",
        merchant_id="MER_1",
        amount=1000.0,
        payment_method="UPI",
        bank="HDFC",
        device_id="DEVICE_1",
        status="SUCCESS",
        failure_reason=None,
        event_time=datetime(2026, 9, 1, 12, 0, 0),
    )
    defaults.update({k: v for k, v in overrides.items() if k != "n"})
    event = PaymentEvent(**defaults)
    db.add(event)
    db.commit()
    db.refresh(event)
    return event


def test_cold_start_customer_gets_neutral_features(db):
    event = _add(db, n=1, amount=5000.0, device_id="DEVICE_9")
    f = extract_features(db, event)
    assert f.prior_event_count == 0
    assert f.amount_ratio_to_typical == 1.0
    assert f.is_new_device is False          # no history -> can't call it new
    assert f.is_new_payment_method is False
    assert f.customer_history_good is False   # not enough history to vouch for


def test_amount_ratio_is_relative_to_prior_successful_spend(db):
    for i in range(4):
        _add(db, n=i, amount=1000.0)
    event = _add(db, n=9, amount=8000.0)
    f = extract_features(db, event)
    assert f.amount_ratio_to_typical == pytest.approx(8.0, rel=1e-3)
    assert any("typical spend" in s for s in f.signals)


def test_new_device_is_flagged_once_history_exists(db):
    for i in range(3):
        _add(db, n=i, device_id="DEVICE_1")
    event = _add(db, n=9, device_id="DEVICE_42")
    f = extract_features(db, event)
    assert f.is_new_device is True
    assert any("device not previously seen" in s for s in f.signals)


def test_recent_failed_count_is_the_consecutive_streak(db):
    _add(db, n=0, status="SUCCESS")
    for i in range(1, 4):
        _add(db, n=i, status="FAILED", failure_reason="BANK_TIMEOUT")
    event = _add(db, n=9, status="FAILED", failure_reason="BANK_TIMEOUT")
    f = extract_features(db, event)
    assert f.recent_failed_count == 3       # the three failures since the last success


def test_streak_resets_after_a_success(db):
    for i in range(3):
        _add(db, n=i, status="FAILED", failure_reason="BANK_TIMEOUT")
    _add(db, n=5, status="SUCCESS")
    event = _add(db, n=9, status="FAILED", failure_reason="BANK_TIMEOUT")
    f = extract_features(db, event)
    assert f.recent_failed_count == 0


def test_unusual_hour_matches_the_training_boundary(db):
    event = _add(db, n=1, event_time=datetime(2026, 9, 1, 3, 30, 0))
    assert extract_features(db, event).is_unusual_hour is True
    event2 = _add(db, n=2, event_time=datetime(2026, 9, 1, 14, 0, 0))
    assert extract_features(db, event2).is_unusual_hour is False


def test_established_customer_with_mostly_successes_has_good_history(db):
    for i in range(9):
        _add(db, n=i, status="SUCCESS")
    _add(db, n=10, status="FAILED", failure_reason="CARD_DECLINED")
    event = _add(db, n=11, status="FAILED", failure_reason="CARD_DECLINED")
    f = extract_features(db, event)
    assert f.customer_history_good is True


def test_model_input_has_exactly_the_trained_features(db):
    event = _add(db, n=1)
    keys = set(extract_features(db, event).as_model_input().keys())
    assert keys == {
        "amount", "amount_ratio_to_typical", "is_new_device",
        "is_new_payment_method", "is_unusual_hour", "recent_failed_count",
    }
