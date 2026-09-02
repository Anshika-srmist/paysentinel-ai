"""Policy transparency, customer drill-down, and timeline endpoints."""
import os
import sys
import uuid

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def _seed_customer(cid, n=5, amount=1000.0):
    for i in range(n):
        client.post("/payments", json={
            "transaction_id": f"TXN_{uuid.uuid4().hex[:10].upper()}",
            "customer_id": cid, "merchant_id": "MER_1", "amount": amount + i,
            "payment_method": "UPI", "bank": "HDFC", "device_id": "DEVICE_1",
            "status": "SUCCESS", "failure_reason": None, "event_time": "2026-09-01T12:00:00",
        })


def test_policy_exposes_rules_thresholds_and_model():
    p = client.get("/policy").json()
    assert p["thresholds"]["hold_above"] == 0.9
    assert [r["outcome"] for r in p["rules"]] == ["HOLD", "RETRY", "OFFER_ALTERNATIVE", "VERIFY", "APPROVE"]
    assert p["model"]["name"]
    fi = p["model"]["feature_importances"]
    assert fi and abs(sum(fi.values()) - 1.0) < 0.05          # importances ~ sum to 1
    assert set(p["actions"]) == {"APPROVE", "RETRY", "OFFER_ALTERNATIVE", "VERIFY", "HOLD"}


def test_customer_profile_is_aggregate_only():
    cid = f"CUST_INS_{uuid.uuid4().hex[:6]}"
    _seed_customer(cid, n=6)
    prof = client.get(f"/customers/{cid}").json()
    assert prof["customer_id"] == cid
    assert prof["total_events"] == 6
    assert prof["success_rate"] == 1.0
    assert prof["history_good"] is True
    assert prof["usual_payment_method"] == "UPI"
    # deliberately NOT an itemised transaction log
    assert "history" not in prof


def test_unknown_customer_is_404():
    assert client.get("/customers/NOBODY_HERE").status_code == 404


def test_timeline_endpoint_is_gone():
    assert client.get("/stats/timeline").status_code == 404
