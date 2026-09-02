"""
Optional anomaly scorer (Isolation Forest). Not wired into the pipeline;
these just check the standalone contract.
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest

from app.engine.anomaly import anomaly_score, is_available

_NORMAL = dict(
    amount=1200.0, amount_ratio_to_typical=1.0, is_new_device=False,
    is_new_payment_method=False, is_unusual_hour=False, recent_failed_count=0,
)
_ANOMALOUS = dict(
    amount=90000.0, amount_ratio_to_typical=45.0, is_new_device=True,
    is_new_payment_method=True, is_unusual_hour=True, recent_failed_count=3,
)


def test_score_is_none_when_model_not_trained():
    if is_available():
        pytest.skip("anomaly model is present; nothing to assert here")
    assert anomaly_score(**_NORMAL) is None


@pytest.mark.skipif(not is_available(), reason="run `python ml/train_anomaly.py` first")
def test_scores_are_in_range_and_order_makes_sense():
    normal = anomaly_score(**_NORMAL)
    anomalous = anomaly_score(**_ANOMALOUS)
    assert 0.0 <= normal <= 1.0
    assert 0.0 <= anomalous <= 1.0
    assert anomalous > normal
