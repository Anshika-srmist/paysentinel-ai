import os
import sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.engine.failure_classifier import FailureCategory
from app.engine.recovery import recovery_probability


def test_successful_payment_has_no_recovery_probability():
    assert recovery_probability(FailureCategory.NONE, 0.1, True, 0) is None


def test_probability_is_always_in_range():
    for category in FailureCategory:
        for risk in (0.0, 0.5, 1.0):
            for fails in (0, 3, 20):
                p = recovery_probability(category, risk, False, fails)
                if category == FailureCategory.NONE:
                    assert p is None
                else:
                    assert 0.01 <= p <= 0.99


def test_categories_are_ordered_by_recoverability():
    kw = dict(risk_score=0.2, customer_history_good=False, recent_failed_count=0)
    temp = recovery_probability(FailureCategory.TEMPORARY, **kw)
    method = recovery_probability(FailureCategory.PAYMENT_METHOD, **kw)
    user = recovery_probability(FailureCategory.USER_RELATED, **kw)
    suspicious = recovery_probability(FailureCategory.SUSPICIOUS, **kw)
    assert temp > method > user > suspicious


def test_higher_risk_lowers_recovery_probability():
    low = recovery_probability(FailureCategory.PAYMENT_METHOD, 0.1, False, 0)
    high = recovery_probability(FailureCategory.PAYMENT_METHOD, 0.85, False, 0)
    assert high < low


def test_repeated_failures_lower_recovery_probability():
    few = recovery_probability(FailureCategory.TEMPORARY, 0.2, False, 1)
    many = recovery_probability(FailureCategory.TEMPORARY, 0.2, False, 6)
    assert many < few


def test_good_history_raises_recovery_probability():
    without = recovery_probability(FailureCategory.PAYMENT_METHOD, 0.2, False, 0)
    with_good = recovery_probability(FailureCategory.PAYMENT_METHOD, 0.2, True, 0)
    assert with_good > without
