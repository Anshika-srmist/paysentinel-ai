"""
Behavioural risk signals.

Turns the engineered feature row into a small set of *scored, evidenced*
signals (LOW / MEDIUM / HIGH / CRITICAL) phrased for an operator — no raw
feature names. The behavioural risk is a fixed weighted sum of the signal
scores, clamped to [0, 1].
"""
from datetime import timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.engine.feature_extractor import Features
from app.models.orm_models import PaymentEvent

_VELOCITY_WINDOW = timedelta(minutes=15)

# Weighted sum -> behavioural_risk. Documented for the audit trail.
_WEIGHTS = {
    "amount_deviation": 0.30,
    "velocity": 0.20,
    "new_device": 0.18,
    "recent_failures": 0.14,
    "new_method": 0.08,
    "unusual_hour": 0.05,
    "new_merchant": 0.05,
}

_BANDS = [(0.85, "critical"), (0.6, "high"), (0.3, "medium"), (0.0, "low")]


def _severity(score: float) -> str:
    for t, label in _BANDS:
        if score >= t:
            return label
    return "low"


def _customer_velocity(db: Session, event: PaymentEvent) -> int:
    lo = event.event_time - _VELOCITY_WINDOW
    rows = db.execute(
        select(PaymentEvent.id)
        .where(PaymentEvent.customer_id == event.customer_id)
        .where(PaymentEvent.event_time >= lo)
        .where(PaymentEvent.event_time <= event.event_time)
        .where(PaymentEvent.id != event.id)
    ).all()
    return len(rows) + 1


def analyse(db: Session, event: PaymentEvent, f: Features) -> dict:
    signals: list[dict] = []
    scores: dict[str, float] = {k: 0.0 for k in _WEIGHTS}
    amount = float(event.amount)

    # amount deviation ------------------------------------------------
    ratio = f.amount_ratio_to_typical
    if ratio >= 1.8 and f.typical_amount:
        s = min(1.0, (ratio - 1.5) / 6.0)
        scores["amount_deviation"] = s
        signals.append({
            "signal": "Amount deviation",
            "severity": _severity(s),
            "evidence": f"₹{amount:,.0f} vs customer's typical ₹{f.typical_amount:,.0f} ({ratio:.1f}x)",
            "contribution": _WEIGHTS["amount_deviation"],
        })

    # velocity ------------------------------------------------------
    vel = _customer_velocity(db, event)
    if vel >= 4:
        s = min(1.0, (vel - 3) / 8.0)
        scores["velocity"] = s
        signals.append({
            "signal": "Transaction velocity",
            "severity": _severity(s),
            "evidence": f"{vel} transactions from this customer in the last 15 min",
            "contribution": _WEIGHTS["velocity"],
        })

    # new device --------------------------------------------------
    if f.is_new_device:
        s = 0.55
        scores["new_device"] = s
        signals.append({
            "signal": "New device",
            "severity": _severity(s),
            "evidence": f"First transaction from {event.device_id} for this customer",
            "contribution": _WEIGHTS["new_device"],
        })

    # recent failures --------------------------------------------
    if f.recent_failed_count >= 2:
        s = min(1.0, f.recent_failed_count / 5.0)
        scores["recent_failures"] = s
        signals.append({
            "signal": "Recent failed attempts",
            "severity": _severity(s),
            "evidence": f"{f.recent_failed_count} consecutive failed attempts before this one",
            "contribution": _WEIGHTS["recent_failures"],
        })

    # new payment method --------------------------------------
    if f.is_new_payment_method:
        s = 0.4
        scores["new_method"] = s
        signals.append({
            "signal": "New payment method",
            "severity": _severity(s),
            "evidence": f"{event.payment_method} not used before by this customer",
            "contribution": _WEIGHTS["new_method"],
        })

    # unusual hour ---------------------------------------------
    if f.is_unusual_hour:
        s = 0.45
        scores["unusual_hour"] = s
        signals.append({
            "signal": "Unusual hour",
            "severity": _severity(s),
            "evidence": f"Transaction at {event.event_time.strftime('%H:%M')} (outside 06:00–23:00)",
            "contribution": _WEIGHTS["unusual_hour"],
        })

    # new merchant ------------------------------------------
    if f.is_new_merchant and ratio >= 2:
        s = 0.35
        scores["new_merchant"] = s
        signals.append({
            "signal": "New merchant",
            "severity": _severity(s),
            "evidence": f"First payment to {event.merchant_id}, at an elevated amount",
            "contribution": _WEIGHTS["new_merchant"],
        })

    behavioral_risk = round(min(1.0, sum(_WEIGHTS[k] * v for k, v in scores.items())), 4)
    return {"behavioral_risk": behavioral_risk, "signals": signals, "weights": _WEIGHTS}
