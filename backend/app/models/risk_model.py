"""
Loads the trained model once at startup and exposes a simple scoring
function. Keeping this separate from ml/train.py so the API doesn't
import training code (sklearn training deps vs. serving deps stay
conceptually separate, even though today they're the same package).
"""
import os
import joblib
import pandas as pd

_MODEL_PATH = os.path.join(os.path.dirname(__file__), "..", "..", "ml", "saved_model.pkl")

_bundle = None


def _load():
    global _bundle
    if _bundle is None:
        _bundle = joblib.load(_MODEL_PATH)
    return _bundle


def score_transaction(amount: float, amount_ratio_to_typical: float, is_new_device: bool,
                       is_new_payment_method: bool, is_unusual_hour: bool,
                       recent_failed_count: int) -> float:
    """Returns a fraud/risk probability in [0, 1]."""
    bundle = _load()
    model = bundle["model"]
    features = bundle["features"]

    row = {
        "amount": amount,
        "amount_ratio_to_typical": amount_ratio_to_typical,
        "is_new_device": int(is_new_device),
        "is_new_payment_method": int(is_new_payment_method),
        "is_unusual_hour": int(is_unusual_hour),
        "recent_failed_count": recent_failed_count,
    }
    row_df = pd.DataFrame([row])[features]
    proba = model.predict_proba(row_df)[0][1]
    return round(float(proba), 4)


def model_name() -> str:
    return _load()["model_name"]
