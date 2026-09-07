"""Rate limiting on the write endpoints + the short-TTL read cache."""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from fastapi.testclient import TestClient

from app.cache import _store, cache_clear
from app.main import app

client = TestClient(app)


def test_assess_is_rate_limited_per_client():
    """30/minute. The 31st call from the same client in the window is a 429,
    not another trip through the scoring pipeline."""
    codes = [
        client.post("/assess", json={"customer_id": f"CUST_RL_{i}", "amount": 100.0, "payment_method": "UPI"}).status_code
        for i in range(35)
    ]
    assert codes.count(200) == 30
    assert codes[-1] == 429
    assert 429 in codes and codes.index(429) == 30


def test_scenario_injector_is_rate_limited():
    """10/minute — it creates real events on every call, so it's capped low."""
    codes = [client.post("/simulate/scenario", json={"name": "normal"}).status_code for _ in range(12)]
    assert codes.count(200) == 10
    assert codes[-1] == 429


def test_stats_summary_is_served_from_cache_within_the_ttl():
    cache_clear()
    first = client.get("/stats/summary").json()
    assert "stats_summary" in _store  # populated on the first call

    # A payment created now must NOT change the cached response until the TTL
    # lapses — staleness is the deliberate trade for not re-aggregating on
    # every poll.
    client.post("/assess", json={"customer_id": "CUST_CACHE_1", "amount": 500.0, "payment_method": "UPI"})
    second = client.get("/stats/summary").json()
    assert second == first

    cache_clear()
    third = client.get("/stats/summary").json()
    assert third["total_payments"] >= first["total_payments"] + 1  # fresh aggregate after the reset
