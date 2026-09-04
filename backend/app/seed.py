"""
First-boot seeding.

Render's free tier has an ephemeral filesystem, so every deploy starts
with an empty SQLite database. `seed_if_empty()` runs from the app's
lifespan startup and, when there are no payment events yet, generates a
realistic batch and scores each one through the full pipeline — so a
fresh deploy always has data on screen (and the live simulator can be
pointed at the deployed URL to add more during a demo).

Self-contained on purpose (no dependency on `simulator/`), with a fixed
seed so the seeded set is reproducible. Controlled by
`PAYSENTINEL_SEED_ON_START` (default "1") and `PAYSENTINEL_SEED_COUNT`.
"""
import os
import random
import uuid
from datetime import datetime, timedelta, timezone


def _utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)

from sqlalchemy.orm import Session

from app.engine.pipeline import process_event
from app.models.orm_models import PaymentEvent, RiskDecision

_BANKS = ["HDFC", "ICICI", "SBI", "Axis", "Kotak", "Yes Bank"]
_METHODS = ["UPI", "CARD", "NETBANKING", "WALLET"]
_DEVICES = [f"DEVICE_{i}" for i in range(1, 30)]
_MERCHANTS = [f"MER_{i}" for i in range(1, 13)]

# A small, fixed customer pool so history accumulates fast enough for
# "established customer" behaviour. Each customer has their OWN device so
# normal traffic carries no spurious network links — the only shared-device
# cluster is the coordinated ring injected below.
_CUSTOMERS = {
    f"CUST_{i}": {
        "low": rng_low,
        "high": rng_high,
        "method": _METHODS[i % len(_METHODS)],
        "device": f"DEVICE_{i}",
    }
    for i, (rng_low, rng_high) in enumerate(
        [(200, 1800), (500, 2500), (800, 3200), (300, 1500), (1000, 4000)] * 4, start=1
    )
}

# --- coordinated ring: the hero network scenario ---------------------
# 4 accounts on one shared device firing similar-amount payments in a
# tight window, mostly to one merchant. Deterministic.
_RING_CUSTOMERS = ["CUST_R1", "CUST_R2", "CUST_R3", "CUST_R4"]
_RING_DEVICE = "DEVICE_RING"
_RING_MERCHANT = "MER_RING"
_RING_AMOUNT = 9000.0


def _ring_events(rng: random.Random) -> list[dict]:
    out = []
    for k in range(13):
        cust = _RING_CUSTOMERS[k % len(_RING_CUSTOMERS)]
        out.append({
            "transaction_id": f"TXN_RING{k:02d}",
            "customer_id": cust,
            "merchant_id": _RING_MERCHANT if k % 5 != 4 else rng.choice(_MERCHANTS),
            "payment_method": "CARD",
            "bank": "HDFC",
            # a tight ~6-minute burst, a few minutes back
            "event_time": _utcnow() - timedelta(minutes=9) + timedelta(seconds=k * 28),
            "device_id": _RING_DEVICE,
            "status": "SUCCESS" if k % 6 else "FAILED",
            "failure_reason": None if k % 6 else "MULTIPLE_FAILED_ATTEMPTS",
            "amount": round(_RING_AMOUNT * rng.uniform(0.975, 1.025), 2),
        })
    return out

_SCENARIOS = ["success", "temporary_failure", "fraud", "repeated_failure", "suspicious"]
_WEIGHTS = [0.60, 0.15, 0.06, 0.12, 0.07]


def _build_event(rng: random.Random, minutes_ago: int) -> dict:
    cid = rng.choice(list(_CUSTOMERS))
    p = _CUSTOMERS[cid]
    scenario = rng.choices(_SCENARIOS, weights=_WEIGHTS, k=1)[0]

    ev = {
        "transaction_id": f"TXN_{uuid.uuid4().hex[:8].upper()}",
        "customer_id": cid,
        "merchant_id": rng.choice(_MERCHANTS),
        "payment_method": p["method"],
        "bank": rng.choice(_BANKS),
        "device_id": p["device"],
        "event_time": _utcnow() - timedelta(minutes=minutes_ago, seconds=rng.randint(0, 59)),
        "status": "SUCCESS",
        "failure_reason": None,
        "amount": round(rng.uniform(p["low"], p["high"]), 2),
    }

    if scenario == "temporary_failure":
        ev["status"] = "FAILED"
        ev["failure_reason"] = rng.choice(["BANK_TIMEOUT", "GATEWAY_TIMEOUT", "NETWORK_ERROR"])
    elif scenario == "fraud":
        ev["amount"] = round(p["high"] * rng.uniform(6, 40), 2)
        ev["device_id"] = rng.choice(_DEVICES)
        ev["status"] = rng.choice(["SUCCESS", "FAILED"])
        ev["failure_reason"] = None if ev["status"] == "SUCCESS" else "SUSPECTED_FRAUD"
    elif scenario == "repeated_failure":
        ev["status"] = "FAILED"
        ev["failure_reason"] = rng.choice(["CARD_DECLINED", "UPI_UNAVAILABLE", "INSUFFICIENT_FUNDS"])
    elif scenario == "suspicious":
        ev["amount"] = round(p["high"] * rng.uniform(3, 8), 2)
        ev["device_id"] = rng.choice(_DEVICES)
        ev["status"] = "FAILED"
        ev["failure_reason"] = "MULTIPLE_FAILED_ATTEMPTS"

    return ev


def seed_if_empty(db: Session, count: int | None = None) -> int:
    """Populate an empty database with `count` scored events. No-op otherwise."""
    if os.getenv("PAYSENTINEL_SEED_ON_START", "1") != "1":
        return 0
    if db.query(PaymentEvent.id).first() is not None:
        return 0

    count = count or int(os.getenv("PAYSENTINEL_SEED_COUNT", "140"))
    rng = random.Random(42)
    made = 0

    # background traffic first (oldest -> newest so "time ago" spreads out)
    batch = [_build_event(rng, int((count - i) * (180 / max(count, 1)))) for i in range(count)]
    # then the coordinated ring, injected near the recent end
    batch += _ring_events(rng)
    batch.sort(key=lambda e: e["event_time"])

    ring_rows: list[PaymentEvent] = []
    for ev in batch:
        row = PaymentEvent(**ev)
        db.add(row)
        db.commit()
        db.refresh(row)
        if row.transaction_id.startswith("TXN_RING"):
            ring_rows.append(row)
        try:
            process_event(db, row)
            made += 1
        except Exception as exc:  # noqa: BLE001
            print(f"[seed] scoring failed for {row.transaction_id}: {exc}")

    # Re-score the ring now that the whole cluster is visible — the earlier
    # events were scored while the pattern was still forming. (A real system
    # re-evaluates risk as connected activity accumulates.)
    for row in ring_rows:
        db.query(RiskDecision).filter(RiskDecision.event_id == row.id).delete()
        db.commit()
        db.refresh(row)
        try:
            process_event(db, row)
        except Exception as exc:  # noqa: BLE001
            print(f"[seed] re-score failed for {row.transaction_id}: {exc}")

    print(f"[seed] inserted {made} scored events (incl. the re-scored coordinated ring)")
    return made
