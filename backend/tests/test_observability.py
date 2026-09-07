"""Request-id propagation, the /ops/metrics snapshot, and the Sentry hook."""
import logging
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from fastapi.testclient import TestClient

from app.main import app
from app.observability import current_request_id, init_sentry

client = TestClient(app)


def test_every_response_carries_a_request_id():
    r = client.get("/health")
    assert r.headers.get("X-Request-ID")


def test_a_supplied_request_id_is_propagated():
    r = client.get("/health", headers={"X-Request-ID": "trace-abc-123"})
    assert r.headers["X-Request-ID"] == "trace-abc-123"


def test_request_id_context_is_cleared_between_requests():
    client.get("/health")
    assert current_request_id() is None  # reset in the middleware's finally block


def test_ops_metrics_counts_requests_and_latency():
    client.get("/health")
    client.get("/stats/summary")
    client.get("/stats/summary")
    snap = client.get("/ops/metrics").json()

    assert snap["requests_total"] >= 3
    assert snap["requests_by_route"]["GET /stats/summary"] == 2
    assert snap["responses_by_status"]["200"] >= 3
    assert snap["latency_ms_by_route"]["/stats/summary"]["samples"] == 2
    assert snap["server_errors_total"] == 0


def test_ops_metrics_records_the_decision_mix():
    for i in range(3):
        client.post("/assess", json={"customer_id": f"CUST_OBS_{i}", "amount": 900.0, "payment_method": "UPI"})
    snap = client.get("/ops/metrics").json()
    assert sum(snap["decisions"].values()) == 3


def test_request_log_line_includes_the_request_id(caplog):
    with caplog.at_level(logging.INFO, logger="paysentinel.request"):
        client.get("/health", headers={"X-Request-ID": "trace-log-check"})
    rec = next(r for r in caplog.records if r.name == "paysentinel.request")
    assert rec.request_id == "trace-log-check"
    assert rec.route == "/health"
    assert rec.status == 200


def test_sentry_is_a_no_op_without_a_dsn(monkeypatch):
    monkeypatch.delenv("SENTRY_DSN", raising=False)
    assert init_sentry() is False
