"""
Trains and compares two risk models on the generated dataset.

Deliberately reports precision/recall/F1/PR-AUC, not accuracy — with a
~13% positive rate, accuracy is a misleading headline metric (a model
that always predicts "not risky" would still score ~87%). PR-AUC is the
more honest single number to lead with on imbalanced data.
"""
import os
import joblib
import pandas as pd
from sklearn.model_selection import train_test_split
from sklearn.linear_model import LogisticRegression
from sklearn.ensemble import RandomForestClassifier
from sklearn.metrics import (
    precision_score, recall_score, f1_score,
    average_precision_score, roc_auc_score, classification_report
)

FEATURES = [
    "amount", "amount_ratio_to_typical", "is_new_device",
    "is_new_payment_method", "is_unusual_hour", "recent_failed_count",
]

HERE = os.path.dirname(__file__)


def load_data() -> pd.DataFrame:
    return pd.read_csv(os.path.join(HERE, "training_data.csv"))


def evaluate(name: str, y_true, y_pred, y_proba) -> dict:
    metrics = {
        "model": name,
        "precision": round(precision_score(y_true, y_pred), 4),
        "recall": round(recall_score(y_true, y_pred), 4),
        "f1": round(f1_score(y_true, y_pred), 4),
        "pr_auc": round(average_precision_score(y_true, y_proba), 4),
        "roc_auc": round(roc_auc_score(y_true, y_proba), 4),
    }
    print(f"\n--- {name} ---")
    for k, v in metrics.items():
        if k != "model":
            print(f"  {k:10s}: {v}")
    print(classification_report(y_true, y_pred, target_names=["normal", "risky"]))
    return metrics


def main():
    df = load_data()
    X = df[FEATURES]
    y = df["is_risky"]

    X_train, X_test, y_train, y_test = train_test_split(
        X, y, test_size=0.2, random_state=42, stratify=y
    )

    results = []

    # --- Baseline: Logistic Regression ---
    logreg = LogisticRegression(class_weight="balanced", max_iter=1000, random_state=42)
    logreg.fit(X_train, y_train)
    logreg_pred = logreg.predict(X_test)
    logreg_proba = logreg.predict_proba(X_test)[:, 1]
    results.append(evaluate("Logistic Regression (baseline)", y_test, logreg_pred, logreg_proba))

    # --- Random Forest ---
    rf = RandomForestClassifier(
        n_estimators=200, max_depth=8, class_weight="balanced",
        random_state=42, n_jobs=-1
    )
    rf.fit(X_train, y_train)
    rf_pred = rf.predict(X_test)
    rf_proba = rf.predict_proba(X_test)[:, 1]
    results.append(evaluate("Random Forest", y_test, rf_pred, rf_proba))

    results_df = pd.DataFrame(results).set_index("model")
    print("\n=== Comparison ===")
    print(results_df.to_string())

    # Pick the winner on PR-AUC (the right metric for this imbalance)
    winner_name = results_df["pr_auc"].idxmax()
    winner_model = rf if "Random Forest" in winner_name else logreg
    print(f"\nSelected model: {winner_name} (highest PR-AUC)")

    # Feature importance (Random Forest only) — useful for the explainability layer
    if winner_model is rf:
        importances = pd.Series(rf.feature_importances_, index=FEATURES).sort_values(ascending=False)
        print("\nFeature importances:")
        print(importances.to_string())

    model_path = os.path.join(HERE, "saved_model.pkl")
    joblib.dump({"model": winner_model, "features": FEATURES, "model_name": winner_name}, model_path)
    print(f"\nSaved winning model -> {model_path}")

    results_df.to_csv(os.path.join(HERE, "model_comparison.csv"))


if __name__ == "__main__":
    main()
