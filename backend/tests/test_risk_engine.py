import json
import os
import sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.engine.failure_classifier import classify_failure, FailureCategory, recommended_action_for
from app.models.risk_model import feature_importances, score_transaction, model_name

_METRICS = json.load(open(os.path.join(os.path.dirname(__file__), "..", "ml", "metrics.json")))


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


def _row(**over):
    base = {
        "amount": 1200, "amount_ratio_to_typical": 1.0, "amount_zscore": 0.0,
        "is_new_device": 0, "is_new_payment_method": 0, "is_unusual_hour": 0,
        "hour_sin": 0.5, "hour_cos": 0.5, "recent_failed_count": 0,
        "customer_fail_ratio": 0.0, "velocity_1h": 0, "velocity_24h": 1,
        "secs_since_last_log": 11.0, "device_shared_count": 0,
    }
    base.update(over)
    return base


def test_risk_model_returns_probability_in_valid_range():
    assert 0.0 <= score_transaction(_row()) <= 1.0


def test_risk_model_scores_obvious_fraud_pattern_higher_than_normal():
    normal = score_transaction(_row())
    fraud_like = score_transaction(_row(
        amount=45000, amount_ratio_to_typical=30.0, amount_zscore=12.0,
        is_new_device=1, is_unusual_hour=1, velocity_1h=9, device_shared_count=3,
    ))
    assert fraud_like > normal


def test_model_name_is_reported():
    assert model_name() in ("Logistic Regression", "Random Forest", "XGBoost", "LightGBM")


def test_score_rejects_an_incomplete_feature_row():
    import pytest
    with pytest.raises(KeyError):
        score_transaction({"amount": 1000})


def test_feature_importances_survive_the_calibration_wrapper():
    # the shipped model is a CalibratedClassifierCV, which hides
    # feature_importances_ — they must still come through, from the bundle.
    fi = feature_importances()
    assert fi is not None
    assert abs(sum(fi.values()) - 1.0) < 0.05


def test_metrics_report_has_cross_validation_and_calibration():
    cv = _METRICS["cross_validation"]
    assert len(cv) >= 2 and all("pr_auc_mean" in r and "pr_auc_std" in r for r in cv)
    # PR-AUC can be a near-tie once velocity features give even LogReg signal
    # on card-testing bursts; the robust differentiator is the false-positive
    # rate — the shipped model must flag far fewer legit payments than the
    # baseline (this gap is many times the fold-to-fold spread).
    winner = max(cv, key=lambda r: r["pr_auc_mean"])
    baseline = next(r for r in cv if "Logistic Regression" in r["model"])
    assert baseline["false_positive_rate_mean"] > 2 * winner["false_positive_rate_mean"]

    cal = _METRICS["calibration"]
    assert cal["brier_score_calibrated"] <= cal["brier_score_uncalibrated"]
    assert len(cal["reliability_curve"]) >= 2


def test_temporal_split_shows_no_meaningful_leakage():
    sv = _METRICS["split_validation"]
    # random-CV PR-AUC minus time-ordered PR-AUC. A large positive gap would
    # mean the random split was leaking future information into the test set.
    assert abs(sv["gap"]) < 0.05
    assert sv["temporal_cv_pr_auc"] > 0.5
