"""`POST /assess` — the synchronous pre-payment risk check."""
import os
import sys
import uuid

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)

VALID = {"APPROVE", "RETRY", "OFFER_ALTERNATIVE", "VERIFY", "HOLD"}


def _assess(**over):
    body = {
        "customer_id": f"CUST_ASSESS_{uuid.uuid4().hex[:6]}",
        "amount": 1500.0,
        "payment_method": "UPI",
    }
    body.update(over)
    return client.post("/assess", json=body)


def test_assess_returns_a_synchronous_verdict():
    r = _assess(amount=900.0)
    assert r.status_code == 200
    body = r.json()
    assert body["decision"] in VALID
    assert body["safe"] is (body["decision"] == "APPROVE")
    assert 0.0 <= body["composite_risk"] <= 1.0
    assert 0.0 <= body["ml_risk"] <= 1.0
    assert body["explanation"]
    assert body["explanation_sections"]["why_this_action"]
    assert body["recommended_action"]
    assert body["transaction_id"].startswith("ASSESS_")


def test_assessed_payment_shows_up_in_the_dashboard_feeds():
    txn = f"TXN_ASSESS_{uuid.uuid4().hex[:8].upper()}"
    cust = f"CUST_ASSESS_{uuid.uuid4().hex[:6]}"
    r = _assess(transaction_id=txn, customer_id=cust, amount=1200.0)
    assert r.status_code == 200

    payments = client.get("/payments", params={"limit": 200}).json()
    mine = next(p for p in payments if p["transaction_id"] == txn)
    assert mine["status"] == "PENDING"

    decisions = client.get("/decisions", params={"limit": 200}).json()
    assert any(d["transaction_id"] == txn for d in decisions)


def test_reusing_a_transaction_id_is_rejected():
    txn = f"TXN_DUP_{uuid.uuid4().hex[:8].upper()}"
    assert _assess(transaction_id=txn).status_code == 200
    r2 = _assess(transaction_id=txn)
    assert r2.status_code == 409


def test_anomalous_attempt_scores_higher_than_a_normal_one():
    cust = f"CUST_ASSESS_{uuid.uuid4().hex[:6]}"
    dev = f"DEV_{uuid.uuid4().hex[:6]}"
    for i in range(6):
        _assess(customer_id=cust, amount=1000.0 + i, device_id=dev)
    normal = _assess(customer_id=cust, amount=1050.0, device_id=dev).json()
    weird = _assess(customer_id=cust, amount=70000.0,
                    device_id=f"NEW_{uuid.uuid4().hex[:6]}", payment_method="CARD").json()
    assert weird["ml_risk"] > normal["ml_risk"]
    assert weird["composite_risk"] >= normal["composite_risk"]


def test_api_key_gate(monkeypatch):
    monkeypatch.setattr("app.main._API_KEY", "s3cret")
    assert _assess().status_code == 401
    r = client.post(
        "/assess",
        json={"customer_id": "CUST_K", "amount": 500.0, "payment_method": "UPI"},
        headers={"X-API-Key": "s3cret"},
    )
    assert r.status_code == 200
