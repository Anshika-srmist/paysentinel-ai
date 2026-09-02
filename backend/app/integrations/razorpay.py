"""
Razorpay webhook adapter.

Point a Razorpay (test-mode) webhook at `POST /webhooks/razorpay` and every
`payment.captured` / `payment.failed` / `payment.authorized` event is mapped
to an internal payment event and scored by the same pipeline the simulator
feeds. This is how PaySentinel connects to a real payment stream — the
simulator is just a stand-in for it.

Signature: Razorpay signs the raw body with your webhook secret
(HMAC-SHA256, hex) and sends it as `X-Razorpay-Signature`. If
`PAYSENTINEL_RAZORPAY_WEBHOOK_SECRET` is set we verify it; if not (local
dev / demo), verification is skipped.
"""
import hashlib
import hmac
import os
from datetime import datetime, timezone

# Razorpay `method` values -> our payment_method vocabulary.
_METHOD_MAP = {
    "upi": "UPI",
    "card": "CARD",
    "netbanking": "NETBANKING",
    "wallet": "WALLET",
    "emi": "CARD",
    "paylater": "WALLET",
}

# Razorpay error reasons -> a failure_reason our classifier understands.
_ERROR_MAP = {
    "payment_failed": "BANK_TIMEOUT",
    "gateway_error": "GATEWAY_TIMEOUT",
    "network_error": "NETWORK_ERROR",
    "bank_error": "BANK_SERVICE_UNAVAILABLE",
    "insufficient_funds": "INSUFFICIENT_FUNDS",
    "card_declined": "CARD_DECLINED",
    "payment_canceled": "INCORRECT_DETAILS",
    "invalid_details": "INCORRECT_DETAILS",
    "fraudulent": "SUSPECTED_FRAUD",
}

_CAPTURED_EVENTS = {"payment.captured", "payment.authorized", "order.paid"}
_FAILED_EVENTS = {"payment.failed"}
SUPPORTED_EVENTS = _CAPTURED_EVENTS | _FAILED_EVENTS


class WebhookError(ValueError):
    """Raised for a malformed or unverifiable webhook."""


def verify_signature(raw_body: bytes, signature: str | None) -> None:
    """Raise WebhookError unless the signature matches (or no secret is configured)."""
    secret = os.getenv("PAYSENTINEL_RAZORPAY_WEBHOOK_SECRET", "").strip()
    if not secret:
        return  # unset => skip verification (dev / demo)
    if not signature:
        raise WebhookError("missing X-Razorpay-Signature header")
    expected = hmac.new(secret.encode(), raw_body, hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected, signature):
        raise WebhookError("signature mismatch")


def to_payment_event(payload: dict) -> dict:
    """
    Map a Razorpay webhook body to the kwargs for a `PaymentEvent`.
    Returns None if the event type isn't one we score.
    """
    event = payload.get("event")
    if event not in SUPPORTED_EVENTS:
        return None

    entity = (
        payload.get("payload", {})
        .get("payment", {})
        .get("entity", {})
    )
    if not entity:
        raise WebhookError("no payment entity in webhook payload")

    notes = entity.get("notes") or {}
    is_success = event in _CAPTURED_EVENTS
    method = _METHOD_MAP.get((entity.get("method") or "").lower(), "CARD")

    failure_reason = None
    if not is_success:
        reason_key = (entity.get("error_reason") or entity.get("error_code") or "payment_failed").lower()
        failure_reason = _ERROR_MAP.get(reason_key, "BANK_TIMEOUT")

    # Razorpay amounts are in the smallest currency unit (paise).
    amount = float(entity.get("amount", 0)) / 100.0

    created_at = entity.get("created_at")
    event_time = (
        datetime.fromtimestamp(created_at, tz=timezone.utc).replace(tzinfo=None)
        if isinstance(created_at, (int, float))
        else datetime.now(timezone.utc).replace(tzinfo=None)
    )

    return {
        "transaction_id": entity.get("id") or f"rzp_{int(datetime.now().timestamp())}",
        # prefer an explicit customer id in notes; else a stable hash of the contact
        "customer_id": str(
            notes.get("customer_id")
            or notes.get("customerId")
            or (f"RZP_{hashlib.sha1((entity.get('email') or entity.get('contact') or 'anon').encode()).hexdigest()[:10].upper()}")
        ),
        "merchant_id": str(notes.get("merchant_id") or entity.get("order_id") or "RZP_MERCHANT"),
        "amount": round(amount, 2),
        "payment_method": method,
        "bank": entity.get("bank") or entity.get("wallet") or None,
        "device_id": str(notes.get("device_id")) if notes.get("device_id") else None,
        "status": "SUCCESS" if is_success else "FAILED",
        "failure_reason": failure_reason,
        "event_time": event_time,
    }
