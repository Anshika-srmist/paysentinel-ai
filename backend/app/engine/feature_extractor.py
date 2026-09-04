"""
Feature extraction — the bridge between a raw ingested payment event and
the interpretable feature row the Day 2 risk model was trained on.

`ml/generate_training_data.py` computes these same features from the
simulator's scenario logic; this module recomputes them at request time
from the customer's *actual* history in the database. The feature names
and the `is_unusual_hour` boundary (06:00–23:00) are kept identical to
the training generator on purpose — a mismatch here silently degrades
the model without raising anything.

For a brand-new customer with no prior events, the "is this unusual FOR
this customer" features can't be judged, so they fall back to neutral
values (ratio 1.0, nothing flagged as new). That is a deliberate
cold-start choice, not an oversight.
"""
from dataclasses import dataclass, field
from typing import List

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.orm_models import PaymentEvent

# How many of the customer's most recent prior events we look at when
# deciding "usual device" / "usual method". Small window keeps it cheap
# and recent-behaviour-weighted.
_HISTORY_WINDOW = 25

# recent_failed_count is capped so a pathological streak can't produce a
# feature value far outside the range the model saw in training.
_MAX_FAILED_STREAK = 10

# A customer needs at least this many prior events before we're willing
# to call their history "good" (used to gate OFFER_ALTERNATIVE).
_MIN_HISTORY_FOR_GOOD = 3
_GOOD_SUCCESS_RATIO = 0.7


@dataclass
class Features:
    """The model input plus the human-readable signals derived alongside it."""

    amount: float
    amount_ratio_to_typical: float
    is_new_device: bool
    is_new_payment_method: bool
    is_unusual_hour: bool
    recent_failed_count: int
    customer_history_good: bool
    prior_event_count: int
    typical_amount: float | None = None
    is_new_merchant: bool = False
    signals: List[str] = field(default_factory=list)

    def as_model_input(self) -> dict:
        """Exactly the keyword arguments `risk_model.score_transaction` expects."""
        return {
            "amount": self.amount,
            "amount_ratio_to_typical": self.amount_ratio_to_typical,
            "is_new_device": self.is_new_device,
            "is_new_payment_method": self.is_new_payment_method,
            "is_unusual_hour": self.is_unusual_hour,
            "recent_failed_count": self.recent_failed_count,
        }

    def as_dict(self) -> dict:
        """Full feature snapshot, persisted with the decision for the Investigation page."""
        return {
            "amount": self.amount,
            "amount_ratio_to_typical": self.amount_ratio_to_typical,
            "is_new_device": self.is_new_device,
            "is_new_payment_method": self.is_new_payment_method,
            "is_unusual_hour": self.is_unusual_hour,
            "recent_failed_count": self.recent_failed_count,
            "customer_history_good": self.customer_history_good,
            "prior_event_count": self.prior_event_count,
        }


def _prior_events(db: Session, event: PaymentEvent) -> List[PaymentEvent]:
    """The customer's events that happened before this one, newest first."""
    stmt = (
        select(PaymentEvent)
        .where(PaymentEvent.customer_id == event.customer_id)
        .where(PaymentEvent.id < event.id)
        .order_by(PaymentEvent.id.desc())
        .limit(_HISTORY_WINDOW)
    )
    return list(db.execute(stmt).scalars().all())


def _typical_amount(prior: List[PaymentEvent]) -> float | None:
    """Mean of prior successful amounts; falls back to all prior amounts."""
    successful = [float(e.amount) for e in prior if e.status == "SUCCESS"]
    pool = successful or [float(e.amount) for e in prior]
    if not pool:
        return None
    return sum(pool) / len(pool)


def _recent_failed_streak(prior: List[PaymentEvent]) -> int:
    """Count of consecutive FAILED events immediately preceding this one."""
    streak = 0
    for e in prior:  # already newest-first
        if e.status == "FAILED":
            streak += 1
        else:
            break
    return min(streak, _MAX_FAILED_STREAK)


def _history_is_good(prior: List[PaymentEvent]) -> bool:
    if len(prior) < _MIN_HISTORY_FOR_GOOD:
        return False
    successes = sum(1 for e in prior if e.status == "SUCCESS")
    return (successes / len(prior)) >= _GOOD_SUCCESS_RATIO


def extract_features(db: Session, event: PaymentEvent) -> Features:
    """
    Build the model feature row (and the plain-English signal list) for a
    single payment event, using the customer's prior events for context.
    The event must already be persisted so it has an `id`.
    """
    prior = _prior_events(db, event)
    amount = float(event.amount)

    typical = _typical_amount(prior)
    ratio = round(amount / typical, 3) if typical else 1.0

    prior_devices = {e.device_id for e in prior if e.device_id}
    prior_methods = {e.payment_method for e in prior if e.payment_method}
    prior_merchants = {e.merchant_id for e in prior if e.merchant_id}

    is_new_device = bool(prior) and event.device_id is not None and event.device_id not in prior_devices
    is_new_method = bool(prior) and event.payment_method is not None and event.payment_method not in prior_methods
    is_new_merchant = bool(prior) and event.merchant_id is not None and event.merchant_id not in prior_merchants

    hour = event.event_time.hour
    is_unusual_hour = not (6 <= hour <= 23)

    recent_failed_count = _recent_failed_streak(prior)

    features = Features(
        amount=amount,
        amount_ratio_to_typical=ratio,
        is_new_device=is_new_device,
        is_new_payment_method=is_new_method,
        is_unusual_hour=is_unusual_hour,
        recent_failed_count=recent_failed_count,
        customer_history_good=_history_is_good(prior),
        prior_event_count=len(prior),
        typical_amount=round(typical, 2) if typical else None,
        is_new_merchant=is_new_merchant,
    )
    features.signals = _build_signals(features)
    return features


def customer_baseline(db: Session, customer_id: str) -> dict:
    """
    The behavioural baseline the model uses for a customer — computed from
    all their events, for the customer drill-down page. Independent of any
    single payment.
    """
    events = list(
        db.execute(
            select(PaymentEvent)
            .where(PaymentEvent.customer_id == customer_id)
            .order_by(PaymentEvent.id.desc())
        ).scalars().all()
    )
    window = events[:_HISTORY_WINDOW]
    devices = [e.device_id for e in window if e.device_id]
    methods = [e.payment_method for e in window if e.payment_method]

    def _mode(values: List[str]) -> str | None:
        return max(set(values), key=values.count) if values else None

    return {
        "typical_amount": round(_typical_amount(window), 2) if _typical_amount(window) else None,
        "usual_device": _mode(devices),
        "usual_payment_method": _mode(methods),
        "recent_failed_streak": _recent_failed_streak(window),
        "history_good": _history_is_good(window),
        "prior_event_count": len(events),
    }


def _build_signals(f: Features) -> List[str]:
    """Human-readable reasons, in roughly descending importance."""
    signals: List[str] = []
    if f.amount_ratio_to_typical >= 3:
        signals.append(
            f"Amount is {f.amount_ratio_to_typical:.1f}x this customer's typical spend"
        )
    if f.is_new_device:
        signals.append("Paid from a device not previously seen for this customer")
    if f.is_new_payment_method:
        signals.append("Used a payment method this customer has not used before")
    if f.recent_failed_count >= 2:
        signals.append(
            f"{f.recent_failed_count} consecutive failed attempts immediately before this one"
        )
    if f.is_unusual_hour:
        signals.append("Occurred at an unusual hour (outside 06:00-23:00)")
    return signals
