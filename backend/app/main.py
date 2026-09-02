"""
PaySentinel AI — FastAPI backend.

Ingests payment events from the simulator, runs each one through the risk
pipeline (feature extraction -> risk score -> failure category ->
decision -> recovery probability -> explanation), persists both the event
and the decision, and exposes them for the dashboard.
"""
import json
import os
import uuid
from contextlib import asynccontextmanager
from typing import List

from fastapi import Depends, FastAPI, Header, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import func, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db.database import Base, SessionLocal, engine, get_db, run_light_migrations
from app.engine.feature_extractor import customer_baseline
from app.engine.pipeline import process_event
from app.integrations import razorpay as rz
from app.models.risk_model import model_name
from app.models.orm_models import PaymentEvent, RiskDecision, _utcnow
from app.models.schemas import (
    AssessRequest,
    AssessResponse,
    CustomerProfile,
    DecisionDetail,
    DecisionListItem,
    PaymentEventIn,
    PaymentEventOut,
    RiskDecisionOut,
    StatsSummary,
)
from app.seed import seed_if_empty

# Optional shared-secret gate for the integration endpoints. Unset => open
# (fine for the demo). Set PAYSENTINEL_API_KEY to require X-API-Key.
_API_KEY = os.getenv("PAYSENTINEL_API_KEY", "").strip()


def require_api_key(x_api_key: str | None = Header(default=None)):
    if _API_KEY and x_api_key != _API_KEY:
        raise HTTPException(status_code=401, detail="invalid or missing X-API-Key")


@asynccontextmanager
async def lifespan(_app: FastAPI):
    # Create/patch the schema at startup rather than import time, so simply
    # importing this module (e.g. in tests, which use their own database)
    # never touches the real SQLite file.
    Base.metadata.create_all(bind=engine)
    run_light_migrations()
    # On a fresh deploy (ephemeral filesystem) give the dashboard data to show.
    with SessionLocal() as db:
        seed_if_empty(db)
    yield


app = FastAPI(title="PaySentinel AI", version="0.4.0", lifespan=lifespan)

# CORS: "*" by default (fine for a public read-only demo); set
# PAYSENTINEL_CORS_ORIGINS to a comma-separated allowlist for production.
_origins_env = os.getenv("PAYSENTINEL_CORS_ORIGINS", "*").strip()
_cors_origins = ["*"] if _origins_env in ("", "*") else [o.strip() for o in _origins_env.split(",") if o.strip()]

app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Decisions that mean "money is not safely through yet".
AT_RISK_DECISIONS = ("VERIFY", "HOLD")


@app.get("/")
def root():
    return {"service": "PaySentinel AI", "status": "running"}


@app.get("/health")
def health(db: Session = Depends(get_db)):
    """Readiness probe for deployment: DB reachable + risk model loaded."""
    checks = {"database": False, "risk_model": False}
    try:
        db.execute(text("SELECT 1"))
        checks["database"] = True
    except Exception as exc:  # noqa: BLE001
        checks["database_error"] = str(exc)
    try:
        checks["risk_model"] = bool(model_name())
        checks["model_name"] = model_name()
    except Exception as exc:  # noqa: BLE001
        checks["risk_model_error"] = str(exc)

    ok = checks["database"] and checks["risk_model"]
    if not ok:
        raise HTTPException(status_code=503, detail=checks)
    return {"status": "ok", **checks}


@app.post("/payments", response_model=PaymentEventOut, status_code=201)
def ingest_payment(event: PaymentEventIn, db: Session = Depends(get_db)):
    db_event = PaymentEvent(**event.model_dump())
    db.add(db_event)
    db.commit()
    db.refresh(db_event)

    # Run the risk pipeline. A failure here must not lose the ingested
    # event, so it's caught and logged rather than surfaced as a 500.
    try:
        process_event(db, db_event)
    except Exception as exc:  # noqa: BLE001
        print(f"[pipeline] failed for {db_event.transaction_id}: {exc}")

    return db_event


@app.post("/assess", response_model=AssessResponse, dependencies=[Depends(require_api_key)])
def assess(req: AssessRequest, db: Session = Depends(get_db)):
    """
    Score a payment that has *not happened yet* and return an action.

    This is the integration entry point — a checkout page, a PSP, or any
    payment flow calls this before confirming and gets APPROVE / VERIFY /
    HOLD (+ a plain-English reason) synchronously. The attempt is recorded
    with status ``PENDING`` so it also shows up in the dashboard.
    """
    txn = req.transaction_id or f"ASSESS_{uuid.uuid4().hex[:10].upper()}"
    event = PaymentEvent(
        transaction_id=txn,
        customer_id=req.customer_id,
        merchant_id=req.merchant_id,
        amount=req.amount,
        payment_method=req.payment_method,
        bank=req.bank,
        device_id=req.device_id,
        status="PENDING",
        failure_reason=None,
        event_time=req.event_time or _utcnow(),
    )
    db.add(event)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=409, detail=f"transaction_id '{txn}' was already assessed")
    db.refresh(event)

    decision = process_event(db, event)
    return AssessResponse(
        transaction_id=txn,
        decision=decision.decision,
        safe=decision.decision == "APPROVE",
        risk_score=float(decision.risk_score),
        recommended_action=decision.recommended_action,
        explanation=decision.explanation,
        signals=json.loads(decision.signals_json) if decision.signals_json else [],
        model_name=decision.model_name,
        decision_id=decision.id,
    )


@app.post("/webhooks/razorpay")
async def razorpay_webhook(
    request: Request,
    db: Session = Depends(get_db),
    x_razorpay_signature: str | None = Header(default=None),
):
    """
    Ingest a Razorpay webhook (`payment.captured` / `payment.failed` / …).
    Auth is the Razorpay signature, not the API key. Idempotent on retry.
    """
    raw = await request.body()
    try:
        rz.verify_signature(raw, x_razorpay_signature)
        payload = json.loads(raw or b"{}")
        mapped = rz.to_payment_event(payload)
    except (rz.WebhookError, json.JSONDecodeError) as exc:
        raise HTTPException(status_code=400, detail=f"bad webhook: {exc}")

    if mapped is None:
        return {"received": True, "scored": False, "reason": f"event '{payload.get('event')}' not scored"}

    if db.query(PaymentEvent.id).filter(PaymentEvent.transaction_id == mapped["transaction_id"]).first():
        return {"received": True, "scored": False, "reason": "already processed"}

    event = PaymentEvent(**mapped)
    db.add(event)
    db.commit()
    db.refresh(event)
    decision = process_event(db, event)
    return {
        "received": True,
        "scored": True,
        "transaction_id": event.transaction_id,
        "decision": decision.decision,
        "risk_score": float(decision.risk_score),
    }


@app.get("/payments", response_model=List[PaymentEventOut])
def list_payments(
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
):
    return (
        db.query(PaymentEvent)
        .order_by(PaymentEvent.id.desc())
        .offset(offset)
        .limit(limit)
        .all()
    )


@app.get("/decisions", response_model=List[DecisionListItem])
def list_decisions(
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
    decision: str | None = Query(None, description="filter by action, e.g. HOLD"),
    db: Session = Depends(get_db),
):
    query = (
        db.query(RiskDecision, PaymentEvent)
        .join(PaymentEvent, RiskDecision.event_id == PaymentEvent.id)
        .order_by(RiskDecision.id.desc())
    )
    if decision:
        query = query.filter(RiskDecision.decision == decision.upper())
    rows = query.offset(offset).limit(limit).all()
    return [
        DecisionListItem(
            decision_id=d.id,
            event_id=e.id,
            transaction_id=e.transaction_id,
            customer_id=e.customer_id,
            amount=float(e.amount),
            status=e.status,
            risk_score=float(d.risk_score),
            failure_category=d.failure_category,
            decision=d.decision,
            recovery_probability=float(d.recovery_probability) if d.recovery_probability is not None else None,
            created_at=d.created_at,
        )
        for d, e in rows
    ]


@app.get("/decisions/{decision_id}", response_model=DecisionDetail)
def get_decision(decision_id: int, db: Session = Depends(get_db)):
    decision = db.get(RiskDecision, decision_id)
    if decision is None:
        raise HTTPException(status_code=404, detail="decision not found")
    event = db.get(PaymentEvent, decision.event_id)

    return DecisionDetail(
        event=PaymentEventOut.model_validate(event),
        decision=RiskDecisionOut.model_validate(decision),
        recommended_action=decision.recommended_action,
        signals=json.loads(decision.signals_json) if decision.signals_json else [],
        features=json.loads(decision.features_json) if decision.features_json else {},
    )


@app.get("/stats/summary", response_model=StatsSummary)
def stats_summary(db: Session = Depends(get_db)):
    total = db.query(func.count(PaymentEvent.id)).scalar() or 0
    successful = (
        db.query(func.count(PaymentEvent.id))
        .filter(PaymentEvent.status == "SUCCESS")
        .scalar()
        or 0
    )
    failed = (
        db.query(func.count(PaymentEvent.id))
        .filter(PaymentEvent.status == "FAILED")
        .scalar()
        or 0
    )

    high_risk = (
        db.query(func.count(RiskDecision.id))
        .filter(RiskDecision.decision.in_(AT_RISK_DECISIONS))
        .scalar()
        or 0
    )
    revenue_at_risk = (
        db.query(func.coalesce(func.sum(PaymentEvent.amount), 0))
        .join(RiskDecision, RiskDecision.event_id == PaymentEvent.id)
        .filter(RiskDecision.decision.in_(AT_RISK_DECISIONS))
        .scalar()
        or 0
    )

    by_action = dict(
        db.query(RiskDecision.decision, func.count(RiskDecision.id))
        .group_by(RiskDecision.decision)
        .all()
    )

    return StatsSummary(
        total_payments=total,
        successful=successful,
        failed=failed,
        high_risk=high_risk,
        revenue_at_risk=float(revenue_at_risk),
        decisions_by_action=by_action,
    )


@app.get("/policy")
def policy():
    """The deterministic decision policy + how the model scores — read-only."""
    from app.engine.decision_engine import Decision, ACTION_TEXT, THRESHOLDS, policy_rules
    from app.engine.recovery import base_rates
    from app.models.risk_model import feature_importances

    return {
        "principle": (
            "The ML model produces a probability, but the final action is chosen by "
            "this deterministic policy — a probabilistic model never makes an "
            "uncontrolled financial decision."
        ),
        "model": {"name": model_name(), "feature_importances": feature_importances()},
        "thresholds": THRESHOLDS,
        "rules": policy_rules(),
        "actions": {d.value: ACTION_TEXT[d] for d in Decision},
        "recovery_base_rates": base_rates(),
    }


@app.get("/customers/{customer_id}", response_model=CustomerProfile)
def get_customer(customer_id: str, db: Session = Depends(get_db)):
    """Aggregate risk signals for a customer — not an itemised payment log."""
    rows = (
        db.query(PaymentEvent, RiskDecision)
        .outerjoin(RiskDecision, RiskDecision.event_id == PaymentEvent.id)
        .filter(PaymentEvent.customer_id == customer_id)
        .all()
    )
    if not rows:
        raise HTTPException(status_code=404, detail=f"no events for customer '{customer_id}'")

    successful = sum(1 for e, _ in rows if e.status == "SUCCESS")
    failed = sum(1 for e, _ in rows if e.status == "FAILED")
    by_action: dict[str, int] = {}
    flagged = 0
    amount_at_risk = 0.0
    for e, d in rows:
        if d is not None:
            by_action[d.decision] = by_action.get(d.decision, 0) + 1
            if d.decision in AT_RISK_DECISIONS:
                flagged += 1
                amount_at_risk += float(e.amount)

    baseline = customer_baseline(db, customer_id)

    return CustomerProfile(
        customer_id=customer_id,
        total_events=len(rows),
        successful=successful,
        failed=failed,
        success_rate=round(successful / len(rows), 4),
        flagged_count=flagged,
        amount_at_risk=round(amount_at_risk, 2),
        history_good=baseline["history_good"],
        typical_amount=baseline["typical_amount"],
        usual_device=baseline["usual_device"],
        usual_payment_method=baseline["usual_payment_method"],
        recent_failed_streak=baseline["recent_failed_streak"],
        prior_event_count=baseline["prior_event_count"],
        decisions_by_action=by_action,
    )
