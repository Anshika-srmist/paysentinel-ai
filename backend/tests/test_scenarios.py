"""Demo scenario injector — fires real events through the real pipeline."""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_lists_available_scenarios():
    names = {s["name"] for s in client.get("/simulate/scenarios").json()["scenarios"]}
    assert names == {"normal", "temporary_failure", "trusted_alt", "new_device_verify",
                     "high_risk_hold", "coordinated_ring"}


def test_unknown_scenario_is_rejected():
    assert client.post("/simulate/scenario", json={"name": "not_a_thing"}).status_code == 400


def test_high_risk_scenario_holds():
    r = client.post("/simulate/scenario", json={"name": "high_risk_hold"})
    assert r.status_code == 200
    body = r.json()
    assert body["events_created"] == 1
    assert body["decisions"][0]["decision"] == "HOLD"
    assert body["hold_count"] == 1


def test_normal_scenario_approves():
    body = client.post("/simulate/scenario", json={"name": "normal"}).json()
    assert body["decisions"][0]["decision"] == "APPROVE"


def test_temporary_failure_scenario_retries():
    body = client.post("/simulate/scenario", json={"name": "temporary_failure"}).json()
    assert body["decisions"][0]["decision"] == "RETRY"


def test_trusted_alt_scenario_offers_alternative():
    body = client.post("/simulate/scenario", json={"name": "trusted_alt"}).json()
    # the 4 history-building events + the failure itself
    assert body["events_created"] == 1
    assert body["decisions"][0]["decision"] == "OFFER_ALTERNATIVE"


def test_coordinated_ring_scenario_produces_at_least_one_hold():
    body = client.post("/simulate/scenario", json={"name": "coordinated_ring"})
    body = body.json()
    assert body["events_created"] == 12
    assert body["hold_count"] >= 1
    assert "HOLD" in {d["decision"] for d in body["decisions"]}


def test_each_run_creates_independent_transactions():
    a = client.post("/simulate/scenario", json={"name": "normal"}).json()
    b = client.post("/simulate/scenario", json={"name": "normal"}).json()
    assert a["decisions"][0]["transaction_id"] != b["decisions"][0]["transaction_id"]
