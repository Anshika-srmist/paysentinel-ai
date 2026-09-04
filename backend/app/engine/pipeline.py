"""
Risk pipeline — one payment event through the whole engine.

    feature engineering
        -> transaction ML risk        (Random Forest)
        -> behavioural risk signals   (scored, evidenced)
        -> network risk analysis      (NetworkX detectors)
        -> rule severity              (deterministic tags)
        -> RISK FUSION                -> composite risk
        -> deterministic policy       -> final decision
        -> recovery plan (if failed)
        -> structured explanation
        -> audit trail
        -> persisted RiskDecision

Called once per ingested event, right after it is saved.
"""
import json

from sqlalchemy.orm import Session

from app.engine import behavioral, network
from app.engine.decision_engine import Decision, action_text, evaluate
from app.engine.explainer import ExplanationContext, explain
from app.engine.failure_classifier import classify_failure
from app.engine.feature_extractor import extract_features
from app.engine.fusion import BLEND, fuse, rule_severity
from app.engine.recovery import recovery_probability
from app.models.orm_models import PaymentEvent, RiskDecision
from app.models.risk_model import model_name, score_transaction


def _audit(event: PaymentEvent, ml: float, beh: float, net: float, severity: str,
           composite: float, rule: str, decision: Decision, has_case: bool) -> list[dict]:
    t = event.event_time
    step = lambda offset, s, d: {"ts": (t.replace(microsecond=0)).isoformat() + f".{offset:03d}", "step": s, "detail": d}
    trail = [
        step(1, "Payment received", f"{event.transaction_id} · ₹{float(event.amount):,.2f} · {event.payment_method}"),
        step(2, "Features generated", f"amount ratio, device/method novelty, failure streak, hour"),
        step(3, "Transaction model scored", f"ML risk {ml:.2f} ({model_name()})"),
        step(4, "Behavioural analysis", f"behavioural risk {beh:.2f}"),
        step(5, "Network analysis", f"network risk {net:.2f}"),
        step(6, "Risk fusion", f"composite {composite:.2f} = {BLEND['ml']}·ML + {BLEND['behavioral']}·beh + {BLEND['network']}·net (severity floor: {severity})"),
        step(7, "Policy evaluated", f"rule fired: {rule}"),
        step(8, "Decision", decision.value),
    ]
    if has_case:
        trail.append(step(9, "Case created", "routed for analyst review"))
    return trail


def process_event(db: Session, event: PaymentEvent) -> RiskDecision:
    features = extract_features(db, event)

    ml_risk = score_transaction(**features.as_model_input())
    beh = behavioral.analyse(db, event, features)
    net = network.analyze_transaction(db, event)

    failure_category = classify_failure(event.status, event.failure_reason, features.recent_failed_count)
    severity = rule_severity(failure_category, event.failure_reason, features.recent_failed_count, net["signals"])

    composite = fuse(ml_risk, beh["behavioral_risk"], net["network_risk"], severity)

    decision, rule = evaluate(composite, failure_category.value, features.customer_history_good)
    if decision == Decision.APPROVE and event.status == "FAILED":
        decision, rule = Decision.RETRY, "failed payment, no blocking condition → safe retry"

    recovery = recovery_probability(
        failure_category, composite, features.customer_history_good, features.recent_failed_count
    )

    sections, source = explain(ExplanationContext(
        transaction_id=event.transaction_id,
        amount=float(event.amount),
        status=event.status,
        decision=decision,
        composite_risk=composite,
        ml_risk=ml_risk,
        behavioral_risk=beh["behavioral_risk"],
        network_risk=net["network_risk"],
        rule_severity=severity,
        failure_category=failure_category,
        recovery_probability=recovery,
        policy_rule=rule,
        network_conclusion=net["conclusion"],
        behavioral_signals=beh["signals"],
        network_signals=net["signals"],
        model_name=model_name(),
    ))

    # combined plain-text signal list (kept for the existing list view)
    flat_signals = [s["evidence"] for s in beh["signals"]] + [s["evidence"] for s in net["signals"]]

    has_case = decision in (Decision.HOLD, Decision.VERIFY)

    db_decision = RiskDecision(
        event_id=event.id,
        risk_score=composite,                       # `risk_score` now = composite
        ml_risk=ml_risk,
        behavioral_risk=beh["behavioral_risk"],
        network_risk=net["network_risk"],
        rule_severity=severity,
        failure_category=failure_category.value,
        decision=decision.value,
        recovery_probability=recovery,
        explanation=sections["summary"],
        explanation_source=source,
        explanation_json=json.dumps(sections),
        recommended_action=action_text(decision),
        model_name=model_name(),
        features_json=json.dumps(features.as_dict()),
        signals_json=json.dumps(flat_signals),
        behavioral_json=json.dumps(beh),
        network_json=json.dumps(net),
        audit_json=json.dumps(_audit(event, ml_risk, beh["behavioral_risk"], net["network_risk"],
                                     severity, composite, rule, decision, has_case)),
    )
    db.add(db_decision)
    db.commit()
    db.refresh(db_decision)
    return db_decision
