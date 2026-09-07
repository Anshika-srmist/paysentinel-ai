"""
Trains and compares the risk models on the generated dataset and writes a
full evaluation report to `ml/metrics.json` (the /model/metrics endpoint
reads that file — nothing in the app fabricates these numbers).

Selection is by **5-fold stratified cross-validation** on PR-AUC, not a
single split — one split's ordering is within noise at this sample size.
A held-out 20% split is still reported for the confusion matrix and
threshold sweep (those need a concrete test set), and the shipped model is
**probability-calibrated** (isotonic) so `score_transaction()` returns a
calibrated P(fraud) from the transaction features, with the Brier score
and a reliability curve recorded.

Metrics reported are precision / recall / F1 / PR-AUC / false-positive
rate — not accuracy, which is misleading at a ~14% positive rate
(predict-always-normal scores ~86%).
"""
import json
import os
from datetime import date

import joblib
import numpy as np
import pandas as pd
from sklearn.calibration import CalibratedClassifierCV, calibration_curve
from sklearn.ensemble import RandomForestClassifier
from sklearn.frozen import FrozenEstimator
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import (
    average_precision_score, brier_score_loss, confusion_matrix, f1_score,
    precision_score, recall_score, roc_auc_score,
)
from sklearn.model_selection import StratifiedKFold, train_test_split

FEATURES = [
    "amount", "amount_ratio_to_typical", "is_new_device",
    "is_new_payment_method", "is_unusual_hour", "recent_failed_count",
]
HERE = os.path.dirname(__file__)
N_FOLDS = 5
RANDOM_STATE = 42


def _make_models() -> dict:
    """Fresh, unfitted estimators — one set per CV fold and for the final fit."""
    return {
        "Logistic Regression + class weighting (baseline)": LogisticRegression(
            class_weight="balanced", max_iter=1000, random_state=RANDOM_STATE
        ),
        "Random Forest + class weighting": RandomForestClassifier(
            n_estimators=200, max_depth=8, class_weight="balanced",
            random_state=RANDOM_STATE, n_jobs=-1,
        ),
    }


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


def _cross_validate(X, y) -> list[dict]:
    """Stratified k-fold. Per model: mean +/- std of each metric across folds."""
    skf = StratifiedKFold(n_splits=N_FOLDS, shuffle=True, random_state=RANDOM_STATE)
    per_model: dict[str, list[dict]] = {name: [] for name in _make_models()}

    for tr_idx, va_idx in skf.split(X, y):
        X_tr, X_va = X.iloc[tr_idx], X.iloc[va_idx]
        y_tr, y_va = y.iloc[tr_idx], y.iloc[va_idx]
        for name, model in _make_models().items():
            model.fit(X_tr, y_tr)
            proba = model.predict_proba(X_va)[:, 1]
            per_model[name].append(_metrics(name, y_va, proba))

    summary = []
    for name, folds in per_model.items():
        row = {"model": name, "folds": N_FOLDS}
        for metric in ("precision", "recall", "f1", "pr_auc", "roc_auc", "false_positive_rate"):
            vals = [f[metric] for f in folds]
            row[f"{metric}_mean"] = round(float(np.mean(vals)), 4)
            row[f"{metric}_std"] = round(float(np.std(vals)), 4)
        summary.append(row)
    return summary


def main():
    df = pd.read_csv(os.path.join(HERE, "training_data.csv"))
    X, y = df[FEATURES], df["is_risky"]

    # 1) model selection — cross-validated
    cv_summary = _cross_validate(X, y)
    for row in cv_summary:
        print(f"\n--- {row['model']} (CV, {N_FOLDS}-fold) ---")
        for m in ("precision", "recall", "f1", "pr_auc", "false_positive_rate"):
            print(f"  {m:20s}: {row[f'{m}_mean']:.4f} +/- {row[f'{m}_std']:.4f}")

    winner_cv = max(cv_summary, key=lambda r: r["pr_auc_mean"])
    winner_name = winner_cv["model"]
    short_name = winner_name.split(" + ")[0].split(" (")[0]
    print(f"\nSelected by mean CV PR-AUC: {winner_name} "
          f"({winner_cv['pr_auc_mean']:.4f} +/- {winner_cv['pr_auc_std']:.4f})")

    # 2) held-out split — for the confusion matrix + threshold sweep the UI
    #    shows. Both models refit here so the numbers stay comparable to the
    #    pre-calibration report.
    X_tr, X_te, y_tr, y_te = train_test_split(
        X, y, test_size=0.2, random_state=RANDOM_STATE, stratify=y
    )
    holdout = []
    winner_proba = None
    for name, model in _make_models().items():
        model.fit(X_tr, y_tr)
        proba = model.predict_proba(X_te)[:, 1]
        holdout.append(_metrics(name, y_te, proba))
        if name == winner_name:
            winner_proba = proba

    # 3) calibration — isotonic, on a dedicated calibration slice. The base
    #    RF is frozen (fit once, on 60% of the data); only the isotonic map
    #    is fit here. Inference is then 1x RF + a cheap monotonic lookup,
    #    which matters because this runs in the /assess request path.
    X_fit, X_cal, y_fit, y_cal = train_test_split(
        X_tr, y_tr, test_size=0.25, random_state=RANDOM_STATE, stratify=y_tr
    )
    base = _make_models()[winner_name]
    base.fit(X_fit, y_fit)
    # Serve single-row predictions on one thread — n_jobs=-1's parallel
    # dispatch overhead dwarfs the compute for a 1-row predict and made
    # /assess ~3x slower than it needs to be.
    if hasattr(base, "n_jobs"):
        base.n_jobs = 1
    # ensemble=False => a single isotonic map over cross-validated predictions
    # of the frozen base, so inference calls the RF once (not once per fold).
    calibrated = CalibratedClassifierCV(FrozenEstimator(base), method="isotonic", ensemble=False)
    calibrated.fit(X_cal, y_cal)

    raw_proba = base.predict_proba(X_te)[:, 1]
    cal_proba = calibrated.predict_proba(X_te)[:, 1]
    frac_pos, mean_pred = calibration_curve(y_te, cal_proba, n_bins=10, strategy="quantile")
    calibration = {
        "method": "isotonic (CalibratedClassifierCV, cv='prefit', 20% calibration slice)",
        "brier_score_uncalibrated": round(float(brier_score_loss(y_te, raw_proba)), 4),
        "brier_score_calibrated": round(float(brier_score_loss(y_te, cal_proba)), 4),
        "reliability_curve": [
            {"mean_predicted": round(float(p), 4), "observed_frequency": round(float(o), 4)}
            for p, o in zip(mean_pred, frac_pos)
        ],
        "note": "Calibrates the ML component only. The composite risk score fuses "
                "ML + behavioural + network + rule severity and remains a risk "
                "indicator, not a calibrated probability.",
    }
    print(f"\nBrier score: {calibration['brier_score_uncalibrated']} (raw) -> "
          f"{calibration['brier_score_calibrated']} (calibrated)")

    # 4) feature importances — from the base fit (the calibrated wrapper hides them)
    importances = None
    if hasattr(base, "feature_importances_"):
        importances = {f: round(float(w), 4) for f, w in zip(FEATURES, base.feature_importances_)}

    # 5) ship the calibrated model. `base` is fit on 60% of the data and
    #    `calibrated` wraps it with the isotonic map fit on the 20%
    #    calibration slice — the same objects just evaluated on the held-out
    #    20%, so the shipped model is the one the report describes.
    final_model = calibrated

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
        "evaluation": (
            f"model selected by {N_FOLDS}-fold stratified CV on PR-AUC; confusion "
            "matrix and threshold sweep from a held-out 20% split; shipped model "
            "is isotonic-calibrated"
        ),
        "selected_model": winner_name,
        "cross_validation": cv_summary,
        "models": holdout,
        "threshold_sweep": _threshold_sweep(y_te, winner_proba),
        "calibration": calibration,
        "feature_importances": importances,
    }

    with open(os.path.join(HERE, "metrics.json"), "w") as fh:
        json.dump(report, fh, indent=2)
    pd.DataFrame(holdout).set_index("model").drop(columns=["confusion_matrix", "threshold"]).to_csv(
        os.path.join(HERE, "model_comparison.csv")
    )
    joblib.dump(
        {
            "model": final_model,
            "features": FEATURES,
            "model_name": short_name,
            "feature_importances": importances,
            "calibrated": True,
        },
        os.path.join(HERE, "saved_model.pkl"),
    )
    print(f"\nWrote metrics.json, model_comparison.csv, saved_model.pkl -> {HERE}")


if __name__ == "__main__":
    main()
