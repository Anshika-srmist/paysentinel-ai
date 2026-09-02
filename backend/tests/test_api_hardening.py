"""Day 4-prep hardening: health probe, pagination bounds, decision filter."""
import os
import sys
import uuid
from datetime import datetime, timedelta

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def _post(**overrides):
    event = {
        "transaction_id": f"TXN_{uuid.uuid4().hex[:10].upper()}",
        "customer_id": f"CUST_HARDEN_{uuid.uuid4().hex[:6]}",
        "merchant_id": "MER_1",
        "amount": 1500.0,
        "payment_method": "UPI",
        "bank": "HDFC",
        "device_id": "DEVICE_1",
        "status": "SUCCESS",
        "failure_reason": None,
        "event_time": datetime(2026, 9, 1, 12, 0, 0).isoformat(),
    }
    event.update(overrides)
    resp = client.post("/payments", json=event)
    assert resp.status_code == 201
    return event["transaction_id"]


def test_health_reports_db_and_model_ok():
    body = client.get("/health").json()
    assert body["status"] == "ok"
    assert body["database"] is True
    assert body["risk_model"] is True
    assert body["model_name"]


def test_payments_pagination_bounds_are_enforced():
    assert client.get("/payments", params={"limit": 0}).status_code == 422
    assert client.get("/payments", params={"limit": 9999}).status_code == 422
    assert client.get("/payments", params={"offset": -1}).status_code == 422


def test_payments_offset_walks_the_list_without_overlap():
    for i in range(5):
        _post(amount=1000.0 + i)
    page1 = client.get("/payments", params={"limit": 2, "offset": 0}).json()
    page2 = client.get("/payments", params={"limit": 2, "offset": 2}).json()
    ids1 = {r["id"] for r in page1}
    ids2 = {r["id"] for r in page2}
    assert len(ids1) == 2 and len(ids2) == 2
    assert ids1.isdisjoint(ids2)


def test_decisions_can_be_filtered_by_action():
    _post(amount=800.0)  # low-risk success -> APPROVE
    rows = client.get("/decisions", params={"decision": "approve", "limit": 200}).json()
    assert rows, "expected at least one APPROVE decision"
    assert all(r["decision"] == "APPROVE" for r in rows)
