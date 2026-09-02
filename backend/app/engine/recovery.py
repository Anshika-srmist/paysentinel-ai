"""
Recovery probability — "if we act on the recommendation, how likely is
this payment to eventually go through?"

The architecture doc names the `recovery_probability` column but leaves
its definition open. This is a transparent heuristic, not a second model:
a base success rate per failure category, adjusted down by risk and by a
run of recent failures, and nudged up for customers with a good history.
It is deliberately simple and easy to swap for a learned estimate later
(e.g. historical retry-success rate per category) without touching the
decision engine or the API.
"""
from app.engine.failure_classifier import FailureCategory

# Base probability that a payment in each category is recoverable at all.
# Temporary/network issues almost always clear on retry; suspicious ones
# rarely turn into a good payment.
_BASE_RATE = {
    FailureCategory.TEMPORARY: 0.90,
    FailureCategory.PAYMENT_METHOD: 0.65,
    FailureCategory.USER_RELATED: 0.45,
    FailureCategory.SUSPICIOUS: 0.15,
}


def recovery_probability(
    failure_category: FailureCategory,
    risk_score: float,
    customer_history_good: bool,
    recent_failed_count: int,
) -> float | None:
    """
    Returns a probability in [0.01, 0.99], or None for a payment that did
    not fail (nothing to recover).
    """
    if failure_category == FailureCategory.NONE:
        return None

    p = _BASE_RATE.get(failure_category, 0.4)

    # Higher risk erodes recovery odds — a risky-looking failure is less
    # likely to be a genuine customer who will succeed on a second try.
    p *= 1.0 - 0.5 * risk_score

    # Each failed attempt beyond the first is a weak negative signal.
    p -= 0.05 * max(0, recent_failed_count - 1)

    # A customer with an established good history gets a modest nudge up.
    if customer_history_good:
        p += 0.10 * (1.0 - p)

    return round(max(0.01, min(0.99, p)), 4)
