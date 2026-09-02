"""
Day 1 tests: ingestion works, and bad input is rejected.
More tests get added alongside the decision engine and failure
classifier in Day 2/3 (test_decision_engine.py, test_failure_classifier.py).
"""
import os
import sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest
from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)

VALID_EVENT = {
    "transaction_id": "TXN_TEST001",
    "customer_id": "CUST_1",
    "merchant_id": "MER_1",
    "amount": 1500.0,
    "payment_method": "UPI",
    "bank": "HDFC",
    "device_id": "DEVICE_1",
    "status": "SUCCESS",
    "failure_reason": None,
    "event_time": "2026-09-01T10:00:00",
}


def test_root():
    resp = client.get("/")
    assert resp.status_code == 200
    assert resp.json()["status"] == "running"


def test_ingest_valid_payment():
    resp = client.post("/payments", json=VALID_EVENT)
    assert resp.status_code == 201
    body = resp.json()
    assert body["transaction_id"] == "TXN_TEST001"
    assert body["status"] == "SUCCESS"


def test_ingest_missing_required_field_rejected():
    bad_event = dict(VALID_EVENT)
    bad_event["transaction_id"] = "TXN_TEST002"
    del bad_event["amount"]
    resp = client.post("/payments", json=bad_event)
    assert resp.status_code == 422  # FastAPI/Pydantic validation error


def test_stats_summary_reflects_ingested_events():
    resp = client.get("/stats/summary")
    assert resp.status_code == 200
    body = resp.json()
    assert body["total_payments"] >= 1
