"""
Decision engine — the deterministic policy layer that sits on top of the
ML risk score.

This is the design point worth defending to judges: *the ML model
produces a probability, but the final action is chosen by a fixed
if/elif policy — a probabilistic model never makes an uncontrolled
financial decision on its own.*

`decide()` is intentionally a direct, line-for-line implementation of the
policy in `docs/ARCHITECTURE.md` §6 so it stays easy to show and explain.
The one operational refinement (never returning APPROVE for a payment
that actually failed) lives in `pipeline.py`, not here, so this function
keeps matching the doc.
"""
from enum import Enum


class Decision(str, Enum):
    APPROVE = "APPROVE"
    RETRY = "RETRY"
    OFFER_ALTERNATIVE = "OFFER_ALTERNATIVE"
    VERIFY = "VERIFY"
    HOLD = "HOLD"


# Short recommended-action text shown on the Investigation page.
ACTION_TEXT = {
    Decision.APPROVE: "No action needed — allow the payment to proceed",
    Decision.RETRY: "Retry the payment automatically after a short delay",
    Decision.OFFER_ALTERNATIVE: "Prompt the customer to try a different payment method",
    Decision.VERIFY: "Hold for a step-up check (OTP / 3-D Secure) before proceeding",
    Decision.HOLD: "Block and route to a human analyst for manual review",
}

# Risk-score thresholds, named so they can be cited in the pitch and
# tuned in one place.
HOLD_THRESHOLD = 0.9
LOW_RISK_THRESHOLD = 0.3


def decide(risk_score: float, failure_category: str, customer_history_good: bool) -> Decision:
    """
    Map (risk score, failure category, history) to a single controlled action.

    `failure_category` is the string value of
    `failure_classifier.FailureCategory` ("temporary", "payment_method",
    "user_related", "suspicious", or "none" for a successful payment).
    """
    if risk_score > HOLD_THRESHOLD:
        return Decision.HOLD
    if failure_category == "temporary" and risk_score < LOW_RISK_THRESHOLD:
        return Decision.RETRY
    if failure_category == "payment_method" and customer_history_good:
        return Decision.OFFER_ALTERNATIVE
    if LOW_RISK_THRESHOLD <= risk_score <= HOLD_THRESHOLD:
        return Decision.VERIFY
    return Decision.APPROVE


def action_text(decision: Decision) -> str:
    return ACTION_TEXT[decision]
