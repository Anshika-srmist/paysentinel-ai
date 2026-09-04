"""
Day 3 end-to-end: POST /payments now runs the full risk pipeline and
persists a decision. These tests hit the real app + SQLite file (like
test_api.py) and use a unique customer per run so they don't depend on
what else is in the database.
"""
import os
import sys
import uuid
from datetime import datetime, timedelta

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest
from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


@pytest.fixture
def customer_id():
    return f"CUST_PIPE_{uuid.uuid4().hex[:8]}"


def _post(customer_id, *, amount, status="SUCCESS", failure_reason=None,
          device_id=None, method="UPI", minutes_ago=0):
    # default: a device private to this customer, so normal traffic carries
    # no spurious network links
    event = {
        "transaction_id": f"TXN_{uuid.uuid4().hex[:10].upper()}",
        "customer_id": customer_id,
        "merchant_id": "MER_1",
        "amount": amount,
        "payment_method": method,
        "bank": "HDFC",
        "device_id": device_id or f"DEV_{customer_id}",
        "status": status,
        "failure_reason": failure_reason,
        "event_time": (datetime(2026, 9, 1, 12, 0, 0) + timedelta(minutes=minutes_ago)).isoformat(),
    }
    resp = client.post("/payments", json=event)
    assert resp.status_code == 201
    return event["transaction_id"]


def _decision_for(txn_id):
    rows = client.get("/decisions", params={"limit": 200}).json()
    match = next((r for r in rows if r["transaction_id"] == txn_id), None)
    assert match is not None, f"no decision persisted for {txn_id}"
    return match


def test_ingesting_a_payment_persists_a_decision(customer_id):
    txn = _post(customer_id, amount=1200.0)
    row = _decision_for(txn)
    assert row["decision"] in {"APPROVE", "RETRY", "OFFER_ALTERNATIVE", "VERIFY", "HOLD"}
    assert 0.0 <= row["risk_score"] <= 1.0


def test_decision_detail_has_an_explanation_and_signals(customer_id):
    txn = _post(customer_id, amount=1200.0)
    decision_id = _decision_for(txn)["decision_id"]

    detail = client.get(f"/decisions/{decision_id}").json()
    assert detail["event"]["transaction_id"] == txn
    assert detail["decision"]["explanation"]                     # non-empty
    assert detail["decision"]["explanation_source"] == "structured"  # LLM off by default
    assert detail["decision"]["model_name"]
    assert detail["recommended_action"]
    assert isinstance(detail["features"], dict) and detail["features"]
    assert detail["explanation_sections"]["why_this_action"]
    assert isinstance(detail["audit"], list) and len(detail["audit"]) >= 5
    assert detail["risk_breakdown"]["composite"] is not None


def test_unknown_decision_id_returns_404():
    assert client.get("/decisions/999999999").status_code == 404


def test_clean_payment_with_good_history_is_approved(customer_id):
    for i in range(6):
        _post(customer_id, amount=1000.0, minutes_ago=i)
    txn = _post(customer_id, amount=1100.0, minutes_ago=10)
    assert _decision_for(txn)["decision"] == "APPROVE"


def test_anomalous_payment_scores_higher_than_a_normal_one(customer_id):
    for i in range(6):
        _post(customer_id, amount=1000.0, minutes_ago=i)

    normal_txn = _post(customer_id, amount=1050.0, minutes_ago=10)
    anomalous_txn = _post(
        customer_id, amount=60000.0, device_id=f"NEW_{uuid.uuid4().hex[:6]}", method="CARD", minutes_ago=11
    )

    normal = _decision_for(normal_txn)
    anomalous = _decision_for(anomalous_txn)
    assert anomalous["ml_risk"] > normal["ml_risk"]
    assert anomalous["risk_score"] >= normal["risk_score"]


def test_stats_summary_reports_decision_breakdown(customer_id):
    _post(customer_id, amount=1000.0)
    body = client.get("/stats/summary").json()
    assert body["total_payments"] >= 1
    assert isinstance(body["decisions_by_action"], dict)
    assert sum(body["decisions_by_action"].values()) >= 1
    assert body["high_risk"] >= 0
