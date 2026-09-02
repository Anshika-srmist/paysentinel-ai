import os
import sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.engine.decision_engine import Decision, action_text, decide
from app.engine.failure_classifier import FailureCategory


def test_very_high_risk_is_held():
    assert decide(0.95, "none", customer_history_good=True) == Decision.HOLD


def test_temporary_failure_low_risk_is_retried():
    assert decide(0.1, "temporary", customer_history_good=True) == Decision.RETRY


def test_temporary_failure_but_elevated_risk_is_not_retried():
    # risk_score not < 0.3 -> falls through to the VERIFY band, not RETRY
    assert decide(0.5, "temporary", customer_history_good=True) == Decision.VERIFY


def test_payment_method_failure_with_good_history_offers_alternative():
    assert decide(0.2, "payment_method", customer_history_good=True) == Decision.OFFER_ALTERNATIVE


def test_payment_method_failure_without_good_history_does_not_offer_alternative():
    # thin/poor history -> the OFFER_ALTERNATIVE branch is skipped
    assert decide(0.1, "payment_method", customer_history_good=False) == Decision.APPROVE


def test_mid_range_risk_is_verified():
    assert decide(0.6, "none", customer_history_good=True) == Decision.VERIFY


def test_low_risk_success_is_approved():
    assert decide(0.05, "none", customer_history_good=True) == Decision.APPROVE


def test_boundary_scores_follow_the_documented_policy():
    # 0.3 and 0.9 are both inside the VERIFY band (inclusive on both ends)
    assert decide(0.30, "none", customer_history_good=True) == Decision.VERIFY
    assert decide(0.90, "none", customer_history_good=True) == Decision.VERIFY
    # just past 0.9 tips into HOLD
    assert decide(0.9001, "none", customer_history_good=True) == Decision.HOLD


def test_decide_accepts_failure_category_enum_value():
    # the pipeline passes FailureCategory(...).value; make sure that path works
    assert decide(0.1, FailureCategory.TEMPORARY.value, customer_history_good=True) == Decision.RETRY


def test_every_decision_has_action_text():
    for decision in Decision:
        assert action_text(decision)
