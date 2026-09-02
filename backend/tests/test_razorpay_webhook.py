"""`POST /webhooks/razorpay` — ingest a real Razorpay payment stream."""
import hashlib
import hmac
import json
import os
import sys
import uuid

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def _captured(pid=None, amount_paise=250000, method="upi", notes=None):
    return {
        "event": "payment.captured",
        "payload": {
            "payment": {
                "entity": {
                    "id": pid or f"pay_{uuid.uuid4().hex[:14]}",
                    "amount": amount_paise,
                    "currency": "INR",
                    "status": "captured",
                    "method": method,
                    "email": "buyer@example.com",
                    "contact": "+919900000000",
                    "notes": notes or {"customer_id": "CUST_RZP_1", "merchant_id": "MER_RZP_1"},
                }
            }
        },
    }


def _failed(reason="insufficient_funds"):
    body = _captured()
    body["event"] = "payment.failed"
    body["payload"]["payment"]["entity"]["status"] = "failed"
    body["payload"]["payment"]["entity"]["error_reason"] = reason
    return body


def test_captured_webhook_is_scored_and_amount_is_converted_from_paise():
    body = _captured(amount_paise=250000)  # ₹2500.00
    r = client.post("/webhooks/razorpay", json=body)
    assert r.status_code == 200
    out = r.json()
    assert out["scored"] is True and out["decision"]

    txn = body["payload"]["payment"]["entity"]["id"]
    detail = client.get("/decisions", params={"limit": 200}).json()
    row = next(d for d in detail if d["transaction_id"] == txn)
    assert row["amount"] == 2500.0
    assert row["status"] == "SUCCESS"


def test_failed_webhook_maps_the_failure_reason():
    body = _failed("insufficient_funds")
    txn = body["payload"]["payment"]["entity"]["id"]
    assert client.post("/webhooks/razorpay", json=body).status_code == 200
    row = next(d for d in client.get("/decisions", params={"limit": 200}).json() if d["transaction_id"] == txn)
    assert row["status"] == "FAILED"
    assert row["failure_category"] in {"user_related", "payment_method", "temporary", "suspicious"}


def test_unsupported_event_is_acknowledged_but_not_scored():
    r = client.post("/webhooks/razorpay", json={"event": "refund.created", "payload": {}})
    assert r.status_code == 200
    assert r.json()["scored"] is False


def test_webhook_is_idempotent_on_retry():
    body = _captured()
    assert client.post("/webhooks/razorpay", json=body).json()["scored"] is True
    again = client.post("/webhooks/razorpay", json=body).json()
    assert again["scored"] is False and "already" in again["reason"]


def test_signature_is_verified_when_a_secret_is_configured(monkeypatch):
    secret = "whsec_test"
    monkeypatch.setenv("PAYSENTINEL_RAZORPAY_WEBHOOK_SECRET", secret)
    body = _captured()
    raw = json.dumps(body).encode()

    bad = client.post("/webhooks/razorpay", content=raw,
                      headers={"Content-Type": "application/json", "X-Razorpay-Signature": "deadbeef"})
    assert bad.status_code == 400

    good_sig = hmac.new(secret.encode(), raw, hashlib.sha256).hexdigest()
    ok = client.post("/webhooks/razorpay", content=raw,
                     headers={"Content-Type": "application/json", "X-Razorpay-Signature": good_sig})
    assert ok.status_code == 200 and ok.json()["scored"] is True
