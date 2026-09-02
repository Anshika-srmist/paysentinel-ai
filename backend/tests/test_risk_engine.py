import os
import sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.engine.failure_classifier import classify_failure, FailureCategory, recommended_action_for
from app.models.risk_model import score_transaction, model_name


def test_temporary_failure_classified_correctly():
    assert classify_failure("FAILED", "BANK_TIMEOUT") == FailureCategory.TEMPORARY


def test_payment_method_failure_classified_correctly():
    assert classify_failure("FAILED", "CARD_DECLINED") == FailureCategory.PAYMENT_METHOD


def test_suspicious_reason_classified_correctly():
    assert classify_failure("FAILED", "SUSPECTED_FRAUD") == FailureCategory.SUSPICIOUS


def test_successful_payment_has_no_category():
    assert classify_failure("SUCCESS", None) == FailureCategory.NONE


def test_unknown_reason_with_repeated_failures_flagged_suspicious():
    assert classify_failure("FAILED", "SOME_NEW_ERROR_CODE", recent_failed_count=4) == FailureCategory.SUSPICIOUS


def test_recommended_action_exists_for_every_category():
    for category in FailureCategory:
        assert recommended_action_for(category)


def test_risk_model_returns_probability_in_valid_range():
    score = score_transaction(
        amount=1500, amount_ratio_to_typical=1.1, is_new_device=False,
        is_new_payment_method=False, is_unusual_hour=False, recent_failed_count=0,
    )
    assert 0.0 <= score <= 1.0


def test_risk_model_scores_obvious_fraud_pattern_higher_than_normal():
    normal_score = score_transaction(
        amount=1200, amount_ratio_to_typical=1.0, is_new_device=False,
        is_new_payment_method=False, is_unusual_hour=False, recent_failed_count=0,
    )
    fraud_like_score = score_transaction(
        amount=45000, amount_ratio_to_typical=30.0, is_new_device=True,
        is_new_payment_method=False, is_unusual_hour=True, recent_failed_count=2,
    )
    assert fraud_like_score > normal_score


def test_model_name_is_reported():
    assert model_name() in ("Logistic Regression (baseline)", "Random Forest")
