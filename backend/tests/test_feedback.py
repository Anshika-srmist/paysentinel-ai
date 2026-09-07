"""Analyst feedback: recording a verdict, correctness, and the summary."""
import os
import sys
import uuid

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from fastapi.testclient import TestClient

from app.main import app, _feedback_correct

client = TestClient(app)


def _assess(**over):
    body = {"customer_id": f"CUST_FB_{uuid.uuid4().hex[:6]}", "amount": 1500.0, "payment_method": "UPI"}
    body.update(over)
    return client.post("/assess", json=body).json()


def test_correctness_helper_covers_every_combination():
    assert _feedback_correct("HOLD", "fraud") is True
    assert _feedback_correct("VERIFY", "fraud") is True
    assert _feedback_correct("HOLD", "legitimate") is False
    assert _feedback_correct("APPROVE", "legitimate") is True
    assert _feedback_correct("APPROVE", "fraud") is False
    # failure-recovery actions aren't a fraud call — not scored
    assert _feedback_correct("RETRY", "fraud") is None
    assert _feedback_correct("OFFER_ALTERNATIVE", "legitimate") is None


def test_feedback_is_recorded_and_shows_on_the_decision():
    d = _assess(amount=800.0)
    did = d["decision_id"]
    r = client.post(f"/decisions/{did}/feedback", json={"verdict": "legitimate", "note": "known customer"})
    assert r.status_code == 200
    body = r.json()
    assert body["verdict"] == "legitimate"
    assert body["engine_decision"] == d["decision"]

    detail = client.get(f"/decisions/{did}").json()
    assert detail["feedback"]["verdict"] == "legitimate"
    assert detail["feedback"]["note"] == "known customer"


def test_resubmitting_replaces_the_previous_verdict():
    did = _assess()["decision_id"]
    client.post(f"/decisions/{did}/feedback", json={"verdict": "fraud"})
    client.post(f"/decisions/{did}/feedback", json={"verdict": "legitimate"})
    assert client.get(f"/decisions/{did}").json()["feedback"]["verdict"] == "legitimate"


def test_feedback_on_unknown_decision_is_404():
    assert client.post("/decisions/987654/feedback", json={"verdict": "fraud"}).status_code == 404


def test_bad_verdict_is_rejected():
    did = _assess()["decision_id"]
    assert client.post(f"/decisions/{did}/feedback", json={"verdict": "maybe"}).status_code == 422


def test_summary_aggregates_labelled_accuracy():
    # a low-risk assess -> APPROVE; label it legitimate -> a correct call (tn)
    d1 = _assess(amount=600.0)
    client.post(f"/decisions/{d1['decision_id']}/feedback", json={"verdict": "legitimate"})
    # label another APPROVE as fraud -> a missed one (fn)
    d2 = _assess(amount=650.0)
    client.post(f"/decisions/{d2['decision_id']}/feedback", json={"verdict": "fraud"})

    s = client.get("/feedback/summary").json()
    assert s["reviewed"] >= 2
    assert s["scored"] >= 2
    assert set(s["confusion"]) == {"tp", "fp", "tn", "fn"}
    assert 0.0 <= s["labelled_accuracy"] <= 1.0
    assert s["by_verdict"].get("fraud", 0) >= 1
