"""
Trains and compares two risk models on the generated dataset, on a
**held-out** test split, and writes a full evaluation report to
`ml/metrics.json` (the /model/metrics endpoint reads that file — nothing
in the app fabricates these numbers).

Deliberately reports precision / recall / F1 / PR-AUC / false-positive
rate, not accuracy — with a ~14% positive rate, accuracy is a misleading
headline (always-predict-normal scores ~86%). PR-AUC and recall/FPR
behaviour are the honest numbers on imbalanced fraud data.
"""
import json
import os
from datetime import date

import joblib
import numpy as np
import pandas as pd
from sklearn.ensemble import RandomForestClassifier
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import (
    average_precision_score, confusion_matrix, f1_score,
    precision_recall_curve, precision_score, recall_score, roc_auc_score,
)
from sklearn.model_selection import train_test_split

FEATURES = [
    "amount", "amount_ratio_to_typical", "is_new_device",
    "is_new_payment_method", "is_unusual_hour", "recent_failed_count",
]
HERE = os.path.dirname(__file__)


def _metrics(name: str, y_true, proba, threshold: float = 0.5) -> dict:
    y_pred = (proba >= threshold).astype(int)
    tn, fp, fn, tp = confusion_matrix(y_true, y_pred, labels=[0, 1]).ravel()
    return {
        "model": name,
        "threshold": threshold,
        "precision": round(precision_score(y_true, y_pred, zero_division=0), 4),
        "recall": round(recall_score(y_true, y_pred, zero_division=0), 4),
        "f1": round(f1_score(y_true, y_pred, zero_division=0), 4),
        "pr_auc": round(average_precision_score(y_true, proba), 4),
        "roc_auc": round(roc_auc_score(y_true, proba), 4),
        "false_positive_rate": round(fp / (fp + tn), 4) if (fp + tn) else 0.0,
        "confusion_matrix": {"tp": int(tp), "fp": int(fp), "tn": int(tn), "fn": int(fn)},
    }


def _threshold_sweep(y_true, proba) -> list[dict]:
    out = []
    for thr in np.round(np.arange(0.10, 0.95, 0.05), 2):
        y_pred = (proba >= thr).astype(int)
        tn, fp, fn, tp = confusion_matrix(y_true, y_pred, labels=[0, 1]).ravel()
        out.append({
            "threshold": float(thr),
            "precision": round(precision_score(y_true, y_pred, zero_division=0), 4),
            "recall": round(recall_score(y_true, y_pred, zero_division=0), 4),
            "false_positives": int(fp),
            "fraud_captured": int(tp),
            "fraud_missed": int(fn),
        })
    return out


def main():
    df = pd.read_csv(os.path.join(HERE, "training_data.csv"))
    X, y = df[FEATURES], df["is_risky"]
    X_tr, X_te, y_tr, y_te = train_test_split(X, y, test_size=0.2, random_state=42, stratify=y)

    logreg = LogisticRegression(class_weight="balanced", max_iter=1000, random_state=42).fit(X_tr, y_tr)
    rf = RandomForestClassifier(
        n_estimators=200, max_depth=8, class_weight="balanced", random_state=42, n_jobs=-1
    ).fit(X_tr, y_tr)

    lr_proba = logreg.predict_proba(X_te)[:, 1]
    rf_proba = rf.predict_proba(X_te)[:, 1]

    lr_m = _metrics("Logistic Regression + class weighting (baseline)", y_te, lr_proba)
    rf_m = _metrics("Random Forest + class weighting", y_te, rf_proba)

    for m in (lr_m, rf_m):
        print(f"\n--- {m['model']} ---")
        for k in ("precision", "recall", "f1", "pr_auc", "roc_auc", "false_positive_rate"):
            print(f"  {k:20s}: {m[k]}")
        print(f"  confusion_matrix     : {m['confusion_matrix']}")

    winner = rf_m if rf_m["pr_auc"] >= lr_m["pr_auc"] else lr_m
    winner_model = rf if winner is rf_m else logreg
    print(f"\nSelected: {winner['model']} (highest PR-AUC on the held-out test set)")

    importances = None
    if hasattr(winner_model, "feature_importances_"):
        importances = {f: round(float(w), 4) for f, w in zip(FEATURES, winner_model.feature_importances_)}

    report = {
        "generated": date.today().isoformat(),
        "dataset": {
            "name": "synthetic payment events (same feature logic as the simulator)",
            "total_records": int(len(df)),
            "training_records": int(len(X_tr)),
            "test_records": int(len(X_te)),
            "positive_rate": round(float(y.mean()), 4),
            "feature_count": len(FEATURES),
        },
        "imbalance_handling": "class_weight='balanced' on both models",
        "evaluation": "held-out 20% stratified test split; no metric computed on training data",
        "selected_model": winner["model"],
        "models": [lr_m, rf_m],
        "threshold_sweep": _threshold_sweep(y_te, rf_proba if winner is rf_m else lr_proba),
        "feature_importances": importances,
    }

    with open(os.path.join(HERE, "metrics.json"), "w") as fh:
        json.dump(report, fh, indent=2)
    pd.DataFrame([lr_m, rf_m]).set_index("model").drop(columns=["confusion_matrix", "threshold"]).to_csv(
        os.path.join(HERE, "model_comparison.csv")
    )
    joblib.dump(
        {"model": winner_model, "features": FEATURES, "model_name": winner["model"].split(" + ")[0].split(" (")[0]},
        os.path.join(HERE, "saved_model.pkl"),
    )
    print(f"\nWrote metrics.json, model_comparison.csv, saved_model.pkl -> {HERE}")


if __name__ == "__main__":
    main()
