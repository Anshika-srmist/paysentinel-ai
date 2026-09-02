"""
Failure classifier — deliberately NOT ML.

Categorizing *why* a payment failed is a lookup problem, not a learning
problem: bank timeouts, card declines, and insufficient-funds errors are
already labeled by the payment gateway/bank. Using ML here would be
solving an easy problem the hard way — worth being able to say this
sentence in the pitch, it signals you know when *not* to reach for ML.
"""
from enum import Enum


class FailureCategory(str, Enum):
    TEMPORARY = "temporary"
    PAYMENT_METHOD = "payment_method"
    USER_RELATED = "user_related"
    SUSPICIOUS = "suspicious"
    NONE = "none"  # payment succeeded, nothing to classify


TEMPORARY_REASONS = {"BANK_TIMEOUT", "GATEWAY_TIMEOUT", "NETWORK_ERROR"}
PAYMENT_METHOD_REASONS = {"UPI_UNAVAILABLE", "CARD_DECLINED", "BANK_SERVICE_UNAVAILABLE"}
USER_RELATED_REASONS = {"INSUFFICIENT_FUNDS", "INCORRECT_DETAILS"}
SUSPICIOUS_REASONS = {"SUSPECTED_FRAUD", "MULTIPLE_FAILED_ATTEMPTS"}

RECOMMENDED_ACTION = {
    FailureCategory.TEMPORARY: "Retry after a short delay",
    FailureCategory.PAYMENT_METHOD: "Suggest an alternative payment method",
    FailureCategory.USER_RELATED: "Ask the customer to correct payment details",
    FailureCategory.SUSPICIOUS: "Require additional verification",
    FailureCategory.NONE: "No action needed",
}


def classify_failure(status: str, failure_reason: str | None, recent_failed_count: int = 0) -> FailureCategory:
    """
    Categorizes a failed payment by cause. Falls back to SUSPICIOUS when
    the failure reason is unrecognized but repeated-failure behavior is
    present — an unknown failure reason combined with a pattern of
    retries is itself a signal worth flagging, even without an ML model.
    """
    if status != "FAILED":
        return FailureCategory.NONE

    if failure_reason in SUSPICIOUS_REASONS:
        return FailureCategory.SUSPICIOUS
    if failure_reason in TEMPORARY_REASONS:
        return FailureCategory.TEMPORARY
    if failure_reason in PAYMENT_METHOD_REASONS:
        return FailureCategory.PAYMENT_METHOD
    if failure_reason in USER_RELATED_REASONS:
        return FailureCategory.USER_RELATED

    # Unrecognized reason + repeated failures -> treat as suspicious rather
    # than silently falling through
    if recent_failed_count >= 3:
        return FailureCategory.SUSPICIOUS

    return FailureCategory.TEMPORARY  # safest default for an unknown-but-single failure


def recommended_action_for(category: FailureCategory) -> str:
    return RECOMMENDED_ACTION[category]
