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


def score_transaction(features: dict) -> float:
    """Calibrated fraud/risk probability in [0, 1].

    `features` is the full feature dict from
    `feature_extractor.Features.as_model_input()`; only the columns the
    model was trained on (bundle['features']) are used, in that order.
    """
    bundle = _load()
    model = bundle["model"]
    cols = bundle["features"]

    missing = [c for c in cols if c not in features]
    if missing:
        raise KeyError(f"score_transaction missing feature(s): {missing}")

    row_df = pd.DataFrame([{c: features[c] for c in cols}])[cols]
    proba = model.predict_proba(row_df)[0][1]
    return round(float(proba), 4)


def model_name() -> str:
    return _load()["model_name"]


def feature_importances() -> dict | None:
    """Per-feature importance for tree models (RandomForest); None for LogReg.

    Read from the bundle: the shipped model is a CalibratedClassifierCV
    wrapper that hides `feature_importances_`, so train.py stores the base
    estimator's importances alongside it.
    """
    bundle = _load()
    stored = bundle.get("feature_importances")
    if stored:
        return {name: round(float(w), 4) for name, w in stored.items()}
    model = bundle["model"]
    if not hasattr(model, "feature_importances_"):
        return None
    return {
        name: round(float(weight), 4)
        for name, weight in zip(bundle["features"], model.feature_importances_)
    }
