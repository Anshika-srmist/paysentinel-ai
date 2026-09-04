"""Network risk engine — graph detectors over a seeded coordinated ring."""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db.database import Base
from app.engine import network
from app.models.orm_models import PaymentEvent
from app.seed import seed_if_empty


@pytest.fixture
def db(monkeypatch):
    monkeypatch.setenv("PAYSENTINEL_SEED_ON_START", "1")
    eng = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(eng)
    s = sessionmaker(bind=eng)()
    seed_if_empty(s, count=80)
    network._cache.update(max_id=-1, events=None, graph=None)   # reset cross-test cache
    try:
        yield s
    finally:
        s.close()


def test_ring_transaction_lights_up_the_network(db):
    ring = db.query(PaymentEvent).filter(PaymentEvent.device_id == "DEVICE_RING").order_by(PaymentEvent.event_time).all()
    res = network.analyze_transaction(db, ring[-1])
    assert res["network_risk"] >= 0.5
    kinds = {s["signal"] for s in res["signals"]}
    assert "Shared device" in kinds
    assert "Transaction velocity" in kinds
    assert res["cluster_size"] >= 4
    assert set(res["connected_accounts"]) >= {"CUST_R1", "CUST_R2", "CUST_R3"} - {ring[-1].customer_id}


def test_normal_transaction_has_negligible_network_risk(db):
    normal = (
        db.query(PaymentEvent)
        .filter(PaymentEvent.device_id != "DEVICE_RING", PaymentEvent.status == "SUCCESS")
        .order_by(PaymentEvent.event_time).first()
    )
    res = network.analyze_transaction(db, normal)
    assert res["network_risk"] < 0.25
    assert res["signals"] == [] or all(s["severity"] in ("low", "medium") for s in res["signals"])


def test_clusters_surface_the_ring(db):
    cl = network.clusters(db)
    ring = next((c for c in cl if set(c["members"]) == {"CUST_R1", "CUST_R2", "CUST_R3", "CUST_R4"}), None)
    assert ring is not None
    assert ring["devices"] == 1 and ring["accounts"] == 4
    assert ring["network_risk"] >= 0.5
    assert ring["status"] == "under_review"


def test_graph_snapshot_is_bounded_and_typed(db):
    g = network.graph_snapshot(db)
    assert 0 < len(g["nodes"]) <= 220
    types = {n["type"] for n in g["nodes"]}
    assert types <= {"customer", "device", "merchant"}
    assert any(n["state"] in ("suspicious", "high") for n in g["nodes"])
