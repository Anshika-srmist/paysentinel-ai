"""
ORM models — mirrors the schema in the architecture doc.

payment_events: raw ingested payment attempts (from the simulator, later
                 from a real Razorpay test-mode webhook if we get there).
risk_decisions: the output of the risk engine for each event — added in
                 Day 2/3, table is created now so migrations don't need
                 to touch this file again.
"""
from datetime import datetime, timezone
from sqlalchemy import Column, Integer, String, Numeric, DateTime, ForeignKey, Text
from app.db.database import Base


def _utcnow() -> datetime:
    # Naive UTC. The timestamp columns are naive DateTime; returning a
    # tz-aware value here is silently truncated by Postgres and inconsistent
    # with the rest of the code (scenarios.py already strips tzinfo by hand).
    return datetime.now(timezone.utc).replace(tzinfo=None)


class PaymentEvent(Base):
    __tablename__ = "payment_events"

    id = Column(Integer, primary_key=True, autoincrement=True)
    transaction_id = Column(String(20), unique=True, nullable=False, index=True)
    customer_id = Column(String(20), nullable=False, index=True)
    merchant_id = Column(String(20))
    amount = Column(Numeric(12, 2), nullable=False)
    payment_method = Column(String(20))
    bank = Column(String(50))
    device_id = Column(String(20))
    status = Column(String(20))            # SUCCESS | FAILED
    failure_reason = Column(String(50), nullable=True)
    event_time = Column(DateTime, nullable=False)
    created_at = Column(DateTime, default=_utcnow)


class RiskDecision(Base):
    __tablename__ = "risk_decisions"

    id = Column(Integer, primary_key=True, autoincrement=True)
    event_id = Column(Integer, ForeignKey("payment_events.id"), nullable=False)
    risk_score = Column(Numeric(5, 4))
    failure_category = Column(String(30), nullable=True)   # temporary | payment_method | user_related | suspicious | none
    decision = Column(String(30))          # APPROVE | RETRY | OFFER_ALTERNATIVE | VERIFY | HOLD
    recovery_probability = Column(Numeric(5, 4), nullable=True)
    explanation = Column(Text, nullable=True)               # LLM- or template-generated plain-English reason

    # Day 3 additions — recorded so the Investigation page can show exactly
    # what the engine saw. All nullable / additive.
    explanation_source = Column(String(20), nullable=True)  # llm | structured
    recommended_action = Column(String(120), nullable=True)
    model_name = Column(String(50), nullable=True)          # which risk model scored this
    features_json = Column(Text, nullable=True)             # the engineered feature snapshot
    signals_json = Column(Text, nullable=True)              # human-readable triggered signals

    # Composite-risk fusion. `risk_score` above now holds the composite; the
    # component scores are kept so the Investigation page can show the breakdown.
    ml_risk = Column(Numeric(5, 4), nullable=True)
    behavioral_risk = Column(Numeric(5, 4), nullable=True)
    network_risk = Column(Numeric(5, 4), nullable=True)
    rule_severity = Column(String(10), nullable=True)       # LOW | MEDIUM | HIGH | CRITICAL
    behavioral_json = Column(Text, nullable=True)           # scored behavioural signals
    network_json = Column(Text, nullable=True)              # network conclusion + signals
    audit_json = Column(Text, nullable=True)                # decision timeline
    explanation_json = Column(Text, nullable=True)          # structured explanation sections

    created_at = Column(DateTime, default=_utcnow)
