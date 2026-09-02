"""
Optional unsupervised anomaly scorer (Isolation Forest).

NOT wired into the pipeline or the decision engine — see the note in
`ml/train_anomaly.py`. Exposed so a dashboard panel or a future decision
rule can ask "how unusual is this event, independent of the supervised
model?" without re-plumbing anything.

`anomaly_score()` returns a value in [0, 1] where 1 = most anomalous and
0.5 sits at the Isolation Forest's own decision threshold (so > 0.5 means
"the model would flag this"). Returns None if the model file hasn't been
trained yet (`python ml/train_anomaly.py`).
"""
import os

import joblib
import pandas as pd

_MODEL_PATH = os.path.join(os.path.dirname(__file__), "..", "..", "ml", "anomaly_model.pkl")

_bundle = None
_missing = False


def _load():
    global _bundle, _missing
    if _bundle is None and not _missing:
        try:
            _bundle = joblib.load(_MODEL_PATH)
        except (FileNotFoundError, OSError):
            _missing = True
    return _bundle


def is_available() -> bool:
    return _load() is not None


def anomaly_score(amount: float, amount_ratio_to_typical: float, is_new_device: bool,
                  is_new_payment_method: bool, is_unusual_hour: bool,
                  recent_failed_count: int) -> float | None:
    bundle = _load()
    if bundle is None:
        return None
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
    # decision_function is centred on 0 at the model's own threshold
    # (negative = anomalous). Map to [0, 1] with 0.5 at the threshold;
    # k=3 spreads the bulk of the data across the range (calibrated on
    # training_data.csv).
    df_val = float(model.decision_function(row_df)[0])
    return round(min(1.0, max(0.0, 0.5 - 3.0 * df_val)), 4)
