"""
The single source of truth for the model's feature vector.

Both sides compute the same features from different sources — the training
generator from a simulated customer timeline, the serving path from the
customer's real history in the database. Any drift between them silently
degrades the model, so the feature list and every derived-value formula
(ratio, z-score, cyclical hour, log recency, clips) live here and are
imported by both.
"""
from __future__ import annotations

import math

# Order is fixed — the trained model's columns depend on it.
FEATURE_NAMES = [
    "amount",
    "amount_ratio_to_typical",
    "amount_zscore",
    "is_new_device",
    "is_new_payment_method",
    "is_unusual_hour",
    "hour_sin",
    "hour_cos",
    "recent_failed_count",
    "customer_fail_ratio",
    "velocity_1h",
    "velocity_24h",
    "secs_since_last_log",
    "device_shared_count",
]

# "Normal" waking transaction window; outside it counts as an unusual hour.
_DAY_START, _DAY_END = 6, 23
# Recency sentinel for a customer's first-ever event: ~30 days, log-scaled.
_NO_PRIOR_SECS = 30 * 24 * 3600
_MAX_FAILED_STREAK = 10
_MAX_DEVICE_SHARING = 20


def is_unusual_hour(hour: int) -> bool:
    return not (_DAY_START <= hour <= _DAY_END)


def cyclical_hour(hour: int) -> tuple[float, float]:
    angle = 2 * math.pi * (hour % 24) / 24
    return round(math.sin(angle), 4), round(math.cos(angle), 4)


def amount_zscore(amount: float, mean: float | None, std: float | None) -> float:
    if not mean or not std or std < 1e-6:
        return 0.0
    return round(max(-5.0, min(15.0, (amount - mean) / std)), 3)


def secs_since_last_log(seconds: float | None) -> float:
    s = _NO_PRIOR_SECS if seconds is None else max(0.0, seconds)
    return round(math.log1p(s), 3)


def assemble(
    *,
    amount: float,
    typical_amount: float | None,
    amount_mean: float | None,
    amount_std: float | None,
    is_new_device: bool,
    is_new_payment_method: bool,
    event_hour: int,
    recent_failed_count: int,
    customer_fail_ratio: float,
    velocity_1h: int,
    velocity_24h: int,
    secs_since_last: float | None,
    device_shared_count: int,
) -> dict:
    """Build the full feature dict from already-computed raw inputs."""
    sin_h, cos_h = cyclical_hour(event_hour)
    ratio = round(amount / typical_amount, 3) if typical_amount else 1.0
    return {
        "amount": round(float(amount), 2),
        "amount_ratio_to_typical": ratio,
        "amount_zscore": amount_zscore(amount, amount_mean, amount_std),
        "is_new_device": int(bool(is_new_device)),
        "is_new_payment_method": int(bool(is_new_payment_method)),
        "is_unusual_hour": int(is_unusual_hour(event_hour)),
        "hour_sin": sin_h,
        "hour_cos": cos_h,
        "recent_failed_count": min(int(recent_failed_count), _MAX_FAILED_STREAK),
        "customer_fail_ratio": round(max(0.0, min(1.0, float(customer_fail_ratio))), 3),
        "velocity_1h": int(velocity_1h),
        "velocity_24h": int(velocity_24h),
        "secs_since_last_log": secs_since_last_log(secs_since_last),
        "device_shared_count": min(int(device_shared_count), _MAX_DEVICE_SHARING),
    }
