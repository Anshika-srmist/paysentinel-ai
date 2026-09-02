"""
Risk pipeline — ties the Day 2 and Day 3 pieces together for one event.

    feature extraction  ->  risk score        (ml model, Day 2)
                        ->  failure category   (rule-based, Day 2)
                        ->  decision           (deterministic policy, Day 3)
                        ->  recovery probability (heuristic, Day 3)
                        ->  explanation         (LLM or template, Day 3)
                        ->  persisted RiskDecision row

Called once per ingested payment event, right after the event is saved.
"""
import json

from sqlalchemy.orm import Session

from app.engine.decision_engine import Decision, action_text, decide
from app.engine.explainer import ExplanationContext, explain
from app.engine.failure_classifier import classify_failure
from app.engine.feature_extractor import extract_features
from app.engine.recovery import recovery_probability
from app.models.orm_models import PaymentEvent, RiskDecision
from app.models.risk_model import model_name, score_transaction


def process_event(db: Session, event: PaymentEvent) -> RiskDecision:
    """Run the full risk pipeline for `event` and persist the resulting decision."""
    features = extract_features(db, event)

    risk_score = score_transaction(**features.as_model_input())

    failure_category = classify_failure(
        event.status, event.failure_reason, features.recent_failed_count
    )

    decision = decide(risk_score, failure_category.value, features.customer_history_good)

    # Operational guard: the policy's fall-through is APPROVE, which only
    # makes sense for a payment that actually succeeded. For a failed
    # payment that isn't risky and isn't a method problem, a plain retry
    # is the safe recommendation. `decide()` itself stays faithful to the
    # architecture doc; this refinement is applied here.
    if decision == Decision.APPROVE and event.status == "FAILED":
        decision = Decision.RETRY

    recovery = recovery_probability(
        failure_category,
        risk_score,
        features.customer_history_good,
        features.recent_failed_count,
    )

    explanation, source = explain(
        ExplanationContext(
            transaction_id=event.transaction_id,
            amount=float(event.amount),
            status=event.status,
            risk_score=risk_score,
            model_name=model_name(),
            failure_category=failure_category,
            decision=decision,
            recovery_probability=recovery,
            customer_history_good=features.customer_history_good,
            signals=features.signals,
        )
    )

    db_decision = RiskDecision(
        event_id=event.id,
        risk_score=risk_score,
        failure_category=failure_category.value,
        decision=decision.value,
        recovery_probability=recovery,
        explanation=explanation,
        explanation_source=source,
        recommended_action=action_text(decision),
        model_name=model_name(),
        features_json=json.dumps(features.as_dict()),
        signals_json=json.dumps(features.signals),
    )
    db.add(db_decision)
    db.commit()
    db.refresh(db_decision)
    return db_decision
