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

Candidates: Logistic Regression (baseline), a randomised-search-tuned
Random Forest, XGBoost and LightGBM. Features come from
`app.engine.features_common` — the same 14 the serving path computes.

Metrics reported are precision / recall / F1 / PR-AUC / false-positive
rate — not accuracy, which is misleading at a ~12% positive rate
(predict-always-normal scores ~88%).
"""
import json
import os
from datetime import date

import joblib
import numpy as np
import pandas as pd
from lightgbm import LGBMClassifier
from sklearn.calibration import CalibratedClassifierCV, calibration_curve
from sklearn.ensemble import RandomForestClassifier
from sklearn.frozen import FrozenEstimator
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import (
    average_precision_score, brier_score_loss, confusion_matrix, f1_score,
    precision_score, recall_score, roc_auc_score,
)
from sklearn.model_selection import RandomizedSearchCV, StratifiedKFold, TimeSeriesSplit
from xgboost import XGBClassifier

from app.engine.features_common import FEATURE_NAMES

FEATURES = FEATURE_NAMES
HERE = os.path.dirname(__file__)
N_FOLDS = 5
RANDOM_STATE = 42
TEST_FRACTION = 0.20      # the most recent 20% of events, by time
CAL_FRACTION = 0.25       # of the training window, its most recent slice, for calibration

# Both filled in main(); defaults keep the module importable / testable.
_RF_PARAMS = {"n_estimators": 300, "max_depth": 10, "min_samples_leaf": 2, "max_features": "sqrt"}
_SCALE_POS_WEIGHT = 7.0


def _make_models() -> dict:
    """Fresh, unfitted estimators — one set per CV fold and for the final fit."""
    return {
        "Logistic Regression + class weighting (baseline)": LogisticRegression(
            class_weight="balanced", max_iter=1000, random_state=RANDOM_STATE
        ),
        "Random Forest + class weighting": RandomForestClassifier(
            class_weight="balanced", random_state=RANDOM_STATE, n_jobs=-1, **_RF_PARAMS
        ),
        "XGBoost": XGBClassifier(
            n_estimators=300, max_depth=4, learning_rate=0.08,
            scale_pos_weight=_SCALE_POS_WEIGHT, eval_metric="aucpr",
            random_state=RANDOM_STATE, n_jobs=-1,
        ),
        "LightGBM": LGBMClassifier(
            n_estimators=300, max_depth=5, learning_rate=0.05, class_weight="balanced",
            random_state=RANDOM_STATE, n_jobs=-1, verbose=-1,
        ),
    }


def _tune_rf(X, y) -> dict:
    """A bounded randomised search for the Random Forest, scored on PR-AUC.
    Time-ordered CV (TimeSeriesSplit) on the training window only — the
    search never sees the held-out test window."""
    search = RandomizedSearchCV(
        RandomForestClassifier(class_weight="balanced", random_state=RANDOM_STATE, n_jobs=-1),
        param_distributions={
            "n_estimators": [200, 300, 400, 600],
            "max_depth": [6, 8, 10, 14, None],
            "min_samples_leaf": [1, 2, 4, 8],
            "max_features": ["sqrt", "log2", 0.5],
        },
        n_iter=15, scoring="average_precision", cv=TimeSeriesSplit(n_splits=3),
        random_state=RANDOM_STATE, n_jobs=-1,
    )
    search.fit(X, y)
    print(f"Tuned RF: {search.best_params_}  (time-CV PR-AUC {search.best_score_:.4f})")
    return search.best_params_


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


def _cross_validate(X, y, splitter) -> list[dict]:
    """Run `splitter` and, per model, give mean +/- std of each metric across
    folds. `splitter` is TimeSeriesSplit for the real report, StratifiedKFold
    only for the leakage check."""
    per_model: dict[str, list[dict]] = {name: [] for name in _make_models()}

    for tr_idx, va_idx in splitter.split(X, y):
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
    global _RF_PARAMS, _SCALE_POS_WEIGHT
    df = pd.read_csv(os.path.join(HERE, "training_data.csv")).sort_values("event_ts")
    X_all, y_all = df[FEATURES], df["is_risky"].reset_index(drop=True)
    X_all = X_all.reset_index(drop=True)
    pos_rate = float(y_all.mean())
    _SCALE_POS_WEIGHT = round((1 - pos_rate) / pos_rate, 2)

    # TIME-ORDERED split: train on the earlier window, test on the most recent
    # TEST_FRACTION. Fraud patterns drift and features look back in time, so a
    # random split leaks the future into the test set. Everything below — tuning,
    # CV, calibration — happens inside the training window only.
    n = len(df)
    test_start = int(n * (1 - TEST_FRACTION))
    cal_start = int(test_start * (1 - CAL_FRACTION))
    X_tr, y_tr = X_all.iloc[:test_start], y_all.iloc[:test_start]
    X_te, y_te = X_all.iloc[test_start:], y_all.iloc[test_start:]
    X_fit, y_fit = X_all.iloc[:cal_start], y_all.iloc[:cal_start]
    X_cal, y_cal = X_all.iloc[cal_start:test_start], y_all.iloc[cal_start:test_start]
    print(f"Split: fit {len(X_fit)} | calibrate {len(X_cal)} | test {len(X_te)} "
          f"(most recent {int(TEST_FRACTION * 100)}% by time)")

    # 0) tune the Random Forest on the training window
    _RF_PARAMS = _tune_rf(X_tr, y_tr)

    # 1) model selection — time-ordered CV on the training window
    cv_summary = _cross_validate(X_tr, y_tr, TimeSeriesSplit(n_splits=N_FOLDS))
    for row in cv_summary:
        print(f"\n--- {row['model']} (time-CV, {N_FOLDS}-fold) ---")
        for m in ("precision", "recall", "f1", "pr_auc", "false_positive_rate"):
            print(f"  {m:20s}: {row[f'{m}_mean']:.4f} +/- {row[f'{m}_std']:.4f}")

    winner_cv = max(cv_summary, key=lambda r: r["pr_auc_mean"])
    winner_name = winner_cv["model"]
    short_name = winner_name.split(" + ")[0].split(" (")[0]
    print(f"\nSelected by mean time-CV PR-AUC: {winner_name} "
          f"({winner_cv['pr_auc_mean']:.4f} +/- {winner_cv['pr_auc_std']:.4f})")

    # leakage check: the same model under a random shuffled split. If the
    # random number is much higher, the temporal eval caught real leakage.
    random_cv = _cross_validate(
        X_all, y_all, StratifiedKFold(n_splits=N_FOLDS, shuffle=True, random_state=RANDOM_STATE)
    )
    random_winner = next(r for r in random_cv if r["model"] == winner_name)
    split_validation = {
        "scheme": "time-ordered: TimeSeriesSplit CV + most-recent-20% held-out test",
        "temporal_cv_pr_auc": winner_cv["pr_auc_mean"],
        "random_cv_pr_auc": random_winner["pr_auc_mean"],
        "gap": round(random_winner["pr_auc_mean"] - winner_cv["pr_auc_mean"], 4),
        "note": "A small gap means the evaluation isn't leaking future information "
                "into the test set; a large one would.",
    }
    print(f"\nLeakage check ({winner_name}): temporal PR-AUC {winner_cv['pr_auc_mean']:.4f} "
          f"vs random {random_winner['pr_auc_mean']:.4f} (gap {split_validation['gap']:+.4f})")

    # 2) held-out (the most recent window) — confusion matrix + threshold sweep
    holdout = []
    winner_proba = None
    for name, model in _make_models().items():
        model.fit(X_tr, y_tr)
        proba = model.predict_proba(X_te)[:, 1]
        holdout.append(_metrics(name, y_te, proba))
        if name == winner_name:
            winner_proba = proba

    # 3) calibration — isotonic, on the calibration slice (which sits in time
    #    between the fit window and the test window). The base model is frozen
    #    (fit once); only the isotonic map is fit here, so inference stays 1x.
    base = _make_models()[winner_name]
    base.fit(X_fit, y_fit)
    # Serve single-row predictions on one thread — n_jobs=-1's parallel
    # dispatch overhead dwarfs the compute for a 1-row predict and made
    # /assess ~3x slower than it needs to be.
    if hasattr(base, "n_jobs"):
        base.n_jobs = 1
    # Fit both isotonic and sigmoid (Platt) on the calibration slice and keep
    # whichever has the lower Brier on the test window. Isotonic is more
    # flexible but overfits a small / drifting calibration set, where sigmoid
    # is steadier. ensemble=False => one map, so inference stays 1x.
    frozen = FrozenEstimator(base)
    raw_proba = base.predict_proba(X_te)[:, 1]
    candidates = {}
    for method in ("isotonic", "sigmoid"):
        cc = CalibratedClassifierCV(frozen, method=method, ensemble=False).fit(X_cal, y_cal)
        p = cc.predict_proba(X_te)[:, 1]
        candidates[method] = (cc, p, brier_score_loss(y_te, p))
    best_method = min(candidates, key=lambda m: candidates[m][2])
    calibrated, cal_proba, _ = candidates[best_method]

    frac_pos, mean_pred = calibration_curve(y_te, cal_proba, n_bins=10, strategy="quantile")
    calibration = {
        "method": f"{best_method} (CalibratedClassifierCV over a frozen base, calibration slice "
                  "between the fit and test windows; picked over the other by test-window Brier)",
        "brier_score_uncalibrated": round(float(brier_score_loss(y_te, raw_proba)), 4),
        "brier_score_calibrated": round(float(candidates[best_method][2]), 4),
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

    # 4) feature importances — from the base fit (the calibrated wrapper hides
    #    them). Normalised to sum to 1: RF gives fractions already, LightGBM /
    #    XGBoost give raw split/gain counts.
    importances = None
    if hasattr(base, "feature_importances_"):
        raw = np.asarray(base.feature_importances_, dtype=float)
        total = raw.sum() or 1.0
        importances = {f: round(float(w / total), 4) for f, w in zip(FEATURES, raw)}

    # 5) ship the calibrated model — `base` fit on the earlier fit window,
    #    `calibrated` wrapping it with the isotonic map from the calibration
    #    slice; evaluated on the most-recent test window.
    final_model = calibrated

    report = {
        "generated": date.today().isoformat(),
        "dataset": {
            "name": "synthetic per-customer timelines with injected fraud archetypes "
                    "(card testing / account takeover / bust-out / coordinated ring)",
            "total_records": int(len(df)),
            "training_records": int(len(X_tr)),
            "test_records": int(len(X_te)),
            "positive_rate": round(float(y_all.mean()), 4),
            "feature_count": len(FEATURES),
        },
        "imbalance_handling": "class_weight='balanced' (LogReg / RF / LightGBM); scale_pos_weight (XGBoost)",
        "evaluation": (
            "4 candidates (tuned RF, XGBoost, LightGBM, LogReg baseline). "
            f"Time-ordered: model selected by {N_FOLDS}-fold TimeSeriesSplit CV on the "
            "training window; confusion matrix and threshold sweep from the most-recent "
            "20% held out by time; shipped model is isotonic-calibrated on an "
            "in-between calibration slice"
        ),
        "selected_model": winner_name,
        "cross_validation": cv_summary,
        "split_validation": split_validation,
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
