"""
Trains an unsupervised anomaly detector (Isolation Forest) on the same
feature rows as the supervised risk model.

Status: this is the "nice-to-have, only if Days 1-4 finish early" item
from ARCHITECTURE.md §2. It is intentionally NOT wired into the ingestion
pipeline or the decision engine — it's a standalone scorer you can turn on
later. It gives a second, independent opinion ("this looks unlike normal
traffic") that doesn't depend on the supervised labels.

    cd backend
    python ml/train_anomaly.py
"""
import os

import joblib
import pandas as pd
from sklearn.ensemble import IsolationForest

FEATURES = [
    "amount", "amount_ratio_to_typical", "is_new_device",
    "is_new_payment_method", "is_unusual_hour", "recent_failed_count",
]

HERE = os.path.dirname(__file__)


def main() -> None:
    df = pd.read_csv(os.path.join(HERE, "training_data.csv"))
    X = df[FEATURES]

    # contamination ≈ the risky rate in the data, so the model's own
    # threshold roughly lines up with "should be flagged".
    contamination = float(df["is_risky"].mean())

    model = IsolationForest(
        n_estimators=200,
        contamination=contamination,
        random_state=42,
        n_jobs=-1,
    )
    model.fit(X)

    # Sanity check: mean raw score for labelled-risky rows should be lower
    # (more anomalous) than for normal rows.
    scores = model.score_samples(X)
    risky_mean = scores[df["is_risky"] == 1].mean()
    normal_mean = scores[df["is_risky"] == 0].mean()
    flagged = (model.predict(X) == -1).mean()
    print(f"contamination      : {contamination:.4f}")
    print(f"mean score risky   : {risky_mean:.4f}")
    print(f"mean score normal  : {normal_mean:.4f}  (higher = more normal)")
    print(f"fraction flagged   : {flagged:.4f}")

    out = os.path.join(HERE, "anomaly_model.pkl")
    joblib.dump({"model": model, "features": FEATURES}, out)
    print(f"\nSaved -> {out}")


if __name__ == "__main__":
    main()
