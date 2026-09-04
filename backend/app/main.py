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
from app.engine import network
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

    d = process_event(db, event)
    net = json.loads(d.network_json) if d.network_json else {}
    return AssessResponse(
        transaction_id=txn,
        decision=d.decision,
        safe=d.decision == "APPROVE",
        composite_risk=float(d.risk_score),
        ml_risk=float(d.ml_risk) if d.ml_risk is not None else None,
        behavioral_risk=float(d.behavioral_risk) if d.behavioral_risk is not None else None,
        network_risk=float(d.network_risk) if d.network_risk is not None else None,
        rule_severity=d.rule_severity,
        recommended_action=d.recommended_action,
        explanation=d.explanation,
        explanation_sections=json.loads(d.explanation_json) if d.explanation_json else {},
        signals=json.loads(d.signals_json) if d.signals_json else [],
        network_conclusion=net.get("conclusion"),
        model_name=d.model_name,
        decision_id=d.id,
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


# --- Razorpay checkout support (for real-mode testing) --------------------
# Test-mode keys from the Razorpay dashboard. Order creation needs the
# secret; the checkout page only needs the (publishable) key id.
_RZP_KEY_ID = os.getenv("RAZORPAY_KEY_ID", "").strip()
_RZP_KEY_SECRET = os.getenv("RAZORPAY_KEY_SECRET", "").strip()

try:
    import razorpay as _razorpay_sdk
except ImportError:  # pragma: no cover
    _razorpay_sdk = None


@app.get("/razorpay/config")
def razorpay_config():
    """What the checkout page needs to know: the publishable key + whether it's wired."""
    return {"enabled": bool(_RZP_KEY_ID and _RZP_KEY_SECRET and _razorpay_sdk), "key_id": _RZP_KEY_ID}


@app.post("/razorpay/order")
def razorpay_order(body: dict):
    """Create a Razorpay order for the checkout page. `body`: {amount, customer_id?}."""
    if not (_RZP_KEY_ID and _RZP_KEY_SECRET and _razorpay_sdk):
        raise HTTPException(status_code=503, detail="Razorpay not configured (set RAZORPAY_KEY_ID / RAZORPAY_KEY_SECRET)")
    try:
        amount = float(body.get("amount", 0))
    except (TypeError, ValueError):
        raise HTTPException(status_code=400, detail="amount must be a number")
    if amount < 1:
        raise HTTPException(status_code=400, detail="amount must be at least ₹1")

    client = _razorpay_sdk.Client(auth=(_RZP_KEY_ID, _RZP_KEY_SECRET))
    notes = {}
    if body.get("customer_id"):
        notes["customer_id"] = str(body["customer_id"])
    if body.get("device_id"):
        notes["device_id"] = str(body["device_id"])
    try:
        order = client.order.create({
            "amount": int(round(amount * 100)),   # paise
            "currency": "INR",
            "notes": notes,
            "payment_capture": 1,
        })
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=502, detail=f"Razorpay order create failed: {exc}")
    return {"order_id": order["id"], "amount": order["amount"], "currency": order["currency"], "key_id": _RZP_KEY_ID}


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
            merchant_id=e.merchant_id,
            payment_method=e.payment_method,
            device_id=e.device_id,
            amount=float(e.amount),
            status=e.status,
            risk_score=float(d.risk_score),
            ml_risk=float(d.ml_risk) if d.ml_risk is not None else None,
            network_risk=float(d.network_risk) if d.network_risk is not None else None,
            failure_category=d.failure_category,
            decision=d.decision,
            recovery_probability=float(d.recovery_probability) if d.recovery_probability is not None else None,
            created_at=d.created_at,
            event_time=e.event_time,
        )
        for d, e in rows
    ]


def _loads(s):
    return json.loads(s) if s else None


@app.get("/decisions/{decision_id}", response_model=DecisionDetail)
def get_decision(decision_id: int, db: Session = Depends(get_db)):
    d = db.get(RiskDecision, decision_id)
    if d is None:
        raise HTTPException(status_code=404, detail="decision not found")
    event = db.get(PaymentEvent, d.event_id)

    return DecisionDetail(
        event=PaymentEventOut.model_validate(event),
        decision=RiskDecisionOut.model_validate(d),
        recommended_action=d.recommended_action,
        signals=_loads(d.signals_json) or [],
        features=_loads(d.features_json) or {},
        behavioral=_loads(d.behavioral_json) or {},
        network=_loads(d.network_json) or {},
        explanation_sections=_loads(d.explanation_json) or {},
        audit=_loads(d.audit_json) or [],
        risk_breakdown={
            "composite": float(d.risk_score) if d.risk_score is not None else None,
            "ml": float(d.ml_risk) if d.ml_risk is not None else None,
            "behavioral": float(d.behavioral_risk) if d.behavioral_risk is not None else None,
            "network": float(d.network_risk) if d.network_risk is not None else None,
            "rule_severity": d.rule_severity,
        },
    )


@app.get("/audit/{transaction_id}")
def get_audit(transaction_id: str, db: Session = Depends(get_db)):
    event = db.query(PaymentEvent).filter(PaymentEvent.transaction_id == transaction_id).first()
    if event is None:
        raise HTTPException(status_code=404, detail="transaction not found")
    d = db.query(RiskDecision).filter(RiskDecision.event_id == event.id).order_by(RiskDecision.id.desc()).first()
    return {"transaction_id": transaction_id, "trail": (_loads(d.audit_json) if d else None) or []}


@app.get("/transactions/{transaction_id}/network")
def transaction_network(transaction_id: str, db: Session = Depends(get_db)):
    event = db.query(PaymentEvent).filter(PaymentEvent.transaction_id == transaction_id).first()
    if event is None:
        raise HTTPException(status_code=404, detail="transaction not found")
    return network.analyze_transaction(db, event)


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
    """The deterministic decision policy + how risk is fused — read-only."""
    from app.engine.decision_engine import Decision, ACTION_TEXT, THRESHOLDS, policy_rules
    from app.engine.fusion import BLEND, SEVERITY_FLOOR
    from app.engine.recovery import base_rates
    from app.models.risk_model import feature_importances

    return {
        "principle": (
            "The model recommends a risk score. The deterministic policy engine "
            "decides the permitted action — a probabilistic model never makes an "
            "uncontrolled financial decision."
        ),
        "model": {"name": model_name(), "feature_importances": feature_importances()},
        "fusion": {
            "formula": "composite = 0.45·ML + 0.20·behavioural + 0.35·network, then raised to a rule-severity floor",
            "blend": BLEND,
            "severity_floor": SEVERITY_FLOOR,
        },
        "thresholds": THRESHOLDS,
        "rules": policy_rules(),
        "actions": {d.value: ACTION_TEXT[d] for d in Decision},
        "recovery_base_rates": base_rates(),
    }


# --- model metrics + analytics -----------------------------------------

_METRICS_PATH = os.path.join(os.path.dirname(__file__), "..", "ml", "metrics.json")


@app.get("/model/metrics")
def model_metrics():
    """Held-out evaluation report (read straight from ml/metrics.json)."""
    try:
        with open(_METRICS_PATH) as fh:
            return json.load(fh)
    except (FileNotFoundError, json.JSONDecodeError):
        raise HTTPException(status_code=503, detail="metrics.json not found — run `python ml/train.py`")


@app.get("/analytics")
def analytics(db: Session = Depends(get_db)):
    """Risk distribution, decision mix, top signals, failure categories."""
    rows = (
        db.query(RiskDecision, PaymentEvent)
        .join(PaymentEvent, RiskDecision.event_id == PaymentEvent.id)
        .all()
    )
    hist = [0] * 10
    by_action: dict[str, int] = {}
    by_failure: dict[str, int] = {}
    signal_counts: dict[str, int] = {}
    for d, e in rows:
        if d.risk_score is not None:
            hist[min(9, int(float(d.risk_score) * 10))] += 1
        by_action[d.decision] = by_action.get(d.decision, 0) + 1
        if d.failure_category and d.failure_category != "none":
            by_failure[d.failure_category] = by_failure.get(d.failure_category, 0) + 1
        for j in (json.loads(d.behavioral_json) if d.behavioral_json else {}).get("signals", []):
            signal_counts[j["signal"]] = signal_counts.get(j["signal"], 0) + 1
        for j in (json.loads(d.network_json) if d.network_json else {}).get("signals", []):
            signal_counts[j["signal"]] = signal_counts.get(j["signal"], 0) + 1

    return {
        "total_decisions": len(rows),
        "risk_histogram": [{"lo": i / 10, "hi": (i + 1) / 10, "count": hist[i]} for i in range(10)],
        "decisions_by_action": by_action,
        "failure_categories": by_failure,
        "top_signals": sorted(
            ({"signal": k, "count": v} for k, v in signal_counts.items()),
            key=lambda x: x["count"], reverse=True,
        )[:8],
    }


@app.get("/analytics/economics")
def analytics_economics(
    avg_fraud_loss: float = Query(38000.0, ge=0, description="Simulation assumption: avg ₹ lost per undetected fraud"),
    avg_false_decline_cost: float = Query(520.0, ge=0, description="Simulation assumption: avg ₹ cost of a wrong decline"),
):
    """
    Decision economics from the held-out confusion matrix. All figures are
    SIMULATED — labelled assumptions, not Razorpay data.
    """
    try:
        with open(_METRICS_PATH) as fh:
            m = json.load(fh)
    except (FileNotFoundError, json.JSONDecodeError):
        raise HTTPException(status_code=503, detail="metrics.json not found — run `python ml/train.py`")

    cm = next(x for x in m["models"] if x["model"] == m["selected_model"])["confusion_matrix"]
    tp, fp, fn = cm["tp"], cm["fp"], cm["fn"]
    prevented = tp * avg_fraud_loss
    missed = fn * avg_fraud_loss
    fp_cost = fp * avg_false_decline_cost
    return {
        "basis": f"held-out test set ({m['dataset']['test_records']} transactions), selected model",
        "assumptions": {
            "avg_fraud_loss": avg_fraud_loss,
            "avg_false_decline_cost": avg_false_decline_cost,
            "note": "Simulation assumptions — not real Razorpay figures.",
        },
        "confusion_matrix": cm,
        "fraud_cases_detected": tp,
        "fraud_cases_missed": fn,
        "false_positives": fp,
        "estimated_prevented_loss": round(prevented, 2),
        "estimated_missed_loss": round(missed, 2),
        "estimated_false_positive_cost": round(fp_cost, 2),
        "net_estimated_impact": round(prevented - fp_cost, 2),
    }


# --- network -------------------------------------------------------

@app.get("/network/graph")
def network_graph(db: Session = Depends(get_db)):
    return network.graph_snapshot(db)


@app.get("/network/clusters")
def network_clusters(db: Session = Depends(get_db)):
    cl = network.clusters(db)
    high = [c for c in cl if c["network_risk"] >= 0.5]
    connected_accounts = sorted({m for c in cl for m in c["members"]})
    return {
        "clusters": cl,
        "summary": {
            "active_clusters": len(cl),
            "high_risk_clusters": len(high),
            "connected_accounts": len(connected_accounts),
            "network_exposure": round(sum(c["volume"] for c in high), 2),
        },
    }


@app.get("/network/entity/{kind}/{ref}")
def network_entity(kind: str, ref: str, db: Session = Depends(get_db)):
    detail = network.entity_detail(db, kind, ref)
    if not detail:
        raise HTTPException(status_code=404, detail="entity not found in the payment graph")
    return detail


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
