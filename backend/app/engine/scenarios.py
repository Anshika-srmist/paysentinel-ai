"""
Demo scenario injector — fires a small, realistic burst of events through the
*real* pipeline (no precomputed results) so a live demo can trigger a
specific outcome on cue instead of only pointing at pre-seeded data.

Each call uses fresh ids/timestamps (now-based), so repeated triggers during
a rehearsal or a live pitch produce independent, inspectable transactions.
"""
import random
import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy.orm import Session

from app.engine.pipeline import process_event
from app.models.orm_models import PaymentEvent, RiskDecision

_METHODS = ["UPI", "CARD", "NETBANKING", "WALLET"]
_MERCHANTS = [f"MER_{i}" for i in range(1, 13)]
_BANKS = ["HDFC", "ICICI", "SBI", "Axis"]


def _now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _txn() -> str:
    return f"TXN_{uuid.uuid4().hex[:8].upper()}"


def _insert(db: Session, **kw) -> PaymentEvent:
    row = PaymentEvent(**kw)
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def _score(db: Session, row: PaymentEvent) -> RiskDecision:
    return process_event(db, row)


def _result(db: Session, rows: list[PaymentEvent], decisions: list[RiskDecision]) -> dict:
    return {
        "events_created": len(rows),
        "decisions": [
            {
                "decision_id": d.id,
                "transaction_id": r.transaction_id,
                "decision": d.decision,
                "risk_score": float(d.risk_score),
            }
            for r, d in zip(rows, decisions)
        ],
        "hold_count": sum(1 for d in decisions if d.decision == "HOLD"),
    }


def _established_customer(db: Session, cust: str, device: str, method: str, amount: float) -> None:
    """Give a fresh customer a short clean history so 'good history' rules apply."""
    for i in range(4):
        row = _insert(
            db, transaction_id=_txn(), customer_id=cust, merchant_id=random.choice(_MERCHANTS),
            amount=round(amount * random.uniform(0.85, 1.15), 2), payment_method=method,
            bank=random.choice(_BANKS), device_id=device, status="SUCCESS", failure_reason=None,
            event_time=_now() - timedelta(minutes=20 - i * 4),
        )
        _score(db, row)


def scenario_normal(db: Session) -> dict:
    cust = f"CUST_DEMO_{uuid.uuid4().hex[:5].upper()}"
    device = f"DEV_{uuid.uuid4().hex[:6].upper()}"
    row = _insert(
        db, transaction_id=_txn(), customer_id=cust, merchant_id=random.choice(_MERCHANTS),
        amount=1450.0, payment_method="UPI", bank="HDFC", device_id=device,
        status="SUCCESS", failure_reason=None, event_time=_now(),
    )
    return _result(db, [row], [_score(db, row)])


def scenario_temporary_failure(db: Session) -> dict:
    cust = f"CUST_DEMO_{uuid.uuid4().hex[:5].upper()}"
    row = _insert(
        db, transaction_id=_txn(), customer_id=cust, merchant_id=random.choice(_MERCHANTS),
        amount=1200.0, payment_method="UPI", bank="ICICI", device_id=f"DEV_{uuid.uuid4().hex[:6].upper()}",
        status="FAILED", failure_reason="BANK_TIMEOUT", event_time=_now(),
    )
    return _result(db, [row], [_score(db, row)])


def scenario_trusted_alt(db: Session) -> dict:
    cust = f"CUST_DEMO_{uuid.uuid4().hex[:5].upper()}"
    device = f"DEV_{uuid.uuid4().hex[:6].upper()}"
    _established_customer(db, cust, device, "UPI", 2000.0)
    row = _insert(
        db, transaction_id=_txn(), customer_id=cust, merchant_id=random.choice(_MERCHANTS),
        amount=2100.0, payment_method="CARD", bank="SBI", device_id=device,
        status="FAILED", failure_reason="CARD_DECLINED", event_time=_now(),
    )
    return _result(db, [row], [_score(db, row)])


def scenario_new_device_verify(db: Session) -> dict:
    cust = f"CUST_DEMO_{uuid.uuid4().hex[:5].upper()}"
    _established_customer(db, cust, f"DEV_{uuid.uuid4().hex[:6].upper()}", "UPI", 1800.0)
    row = _insert(
        db, transaction_id=_txn(), customer_id=cust, merchant_id=random.choice(_MERCHANTS),
        amount=9200.0, payment_method="UPI", bank="HDFC", device_id=f"NEW_{uuid.uuid4().hex[:6].upper()}",
        status="SUCCESS", failure_reason=None, event_time=_now(),
    )
    return _result(db, [row], [_score(db, row)])


def scenario_high_risk_hold(db: Session) -> dict:
    cust = f"CUST_DEMO_{uuid.uuid4().hex[:5].upper()}"
    _established_customer(db, cust, f"DEV_{uuid.uuid4().hex[:6].upper()}", "UPI", 1500.0)
    row = _insert(
        db, transaction_id=_txn(), customer_id=cust, merchant_id=random.choice(_MERCHANTS),
        amount=88000.0, payment_method="CARD", bank="Axis", device_id=f"NEW_{uuid.uuid4().hex[:6].upper()}",
        status="FAILED", failure_reason="SUSPECTED_FRAUD", event_time=_now(),
    )
    return _result(db, [row], [_score(db, row)])


def scenario_coordinated_ring(db: Session) -> dict:
    """The hero: a fresh device shared by 4 fresh accounts, tight burst, similar amounts."""
    device = f"RING_{uuid.uuid4().hex[:6].upper()}"
    merchant = f"MER_{uuid.uuid4().hex[:4].upper()}"
    customers = [f"CUST_RING_{uuid.uuid4().hex[:4].upper()}" for _ in range(4)]
    base_amount = random.choice([6000.0, 9000.0, 15000.0])
    start = _now() - timedelta(minutes=6)

    rows = []
    for k in range(12):
        cust = customers[k % len(customers)]
        row = _insert(
            db, transaction_id=_txn(), customer_id=cust,
            merchant_id=merchant if k % 4 != 3 else random.choice(_MERCHANTS),
            amount=round(base_amount * random.uniform(0.97, 1.03), 2),
            payment_method="CARD", bank=random.choice(_BANKS), device_id=device,
            status="SUCCESS" if k % 6 else "FAILED",
            failure_reason=None if k % 6 else "MULTIPLE_FAILED_ATTEMPTS",
            event_time=start + timedelta(seconds=k * 28),
        )
        rows.append(row)
        _score(db, row)  # progressive: each event scored with only earlier ones visible

    # re-score now the full cluster is visible (mirrors the seeded ring —
    # a real system re-evaluates risk as connected activity accumulates)
    decisions = []
    for r in rows:
        db.query(RiskDecision).filter(RiskDecision.event_id == r.id).delete()
        db.commit()
        decisions.append(_score(db, r))

    return _result(db, rows, decisions)


SCENARIOS = {
    "normal": scenario_normal,
    "temporary_failure": scenario_temporary_failure,
    "trusted_alt": scenario_trusted_alt,
    "new_device_verify": scenario_new_device_verify,
    "high_risk_hold": scenario_high_risk_hold,
    "coordinated_ring": scenario_coordinated_ring,
}

SCENARIO_META = {
    "normal": {"label": "Normal payment", "expect": "APPROVE"},
    "temporary_failure": {"label": "Temporary failure", "expect": "RETRY"},
    "trusted_alt": {"label": "Trusted customer, method failure", "expect": "OFFER_ALTERNATIVE"},
    "new_device_verify": {"label": "New device, elevated amount", "expect": "VERIFY"},
    "high_risk_hold": {"label": "High-risk transaction", "expect": "HOLD"},
    "coordinated_ring": {"label": "Coordinated network attack", "expect": "HOLD"},
}


def run(db: Session, name: str) -> dict:
    if name not in SCENARIOS:
        raise ValueError(f"unknown scenario '{name}'")
    return {"scenario": name, **SCENARIO_META[name], **SCENARIOS[name](db)}
