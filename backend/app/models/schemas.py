from datetime import datetime
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, ConfigDict


class PaymentEventIn(BaseModel):
    """What the simulator (or a real webhook, eventually) sends us."""
    transaction_id: str
    customer_id: str
    merchant_id: Optional[str] = None
    amount: float
    payment_method: str
    bank: Optional[str] = None
    device_id: Optional[str] = None
    status: str                      # SUCCESS | FAILED
    failure_reason: Optional[str] = None
    event_time: datetime


class PaymentEventOut(PaymentEventIn):
    model_config = ConfigDict(from_attributes=True)

    id: int


class RiskDecisionOut(BaseModel):
    """The risk engine's output for one event (Day 3)."""
    id: int
    event_id: int
    risk_score: float
    failure_category: Optional[str] = None
    decision: str
    recovery_probability: Optional[float] = None
    explanation: Optional[str] = None
    explanation_source: Optional[str] = None
    recommended_action: Optional[str] = None
    model_name: Optional[str] = None
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class DecisionListItem(BaseModel):
    """Row for the Live Stream / decisions list — event summary + decision."""
    decision_id: int
    event_id: int
    transaction_id: str
    customer_id: str
    amount: float
    status: str
    risk_score: float
    failure_category: Optional[str] = None
    decision: str
    recovery_probability: Optional[float] = None
    created_at: datetime


class DecisionDetail(BaseModel):
    """Full payload for the Investigation page."""
    event: PaymentEventOut
    decision: RiskDecisionOut
    recommended_action: Optional[str] = None
    signals: List[str] = []
    features: Dict[str, Any] = {}


class StatsSummary(BaseModel):
    total_payments: int
    successful: int
    failed: int
    high_risk: int = 0                        # decisions routed to VERIFY or HOLD
    revenue_at_risk: float = 0.0             # amount tied up in those events
    decisions_by_action: Dict[str, int] = {}


class CustomerProfile(BaseModel):
    """
    Aggregate risk signals for one customer — deliberately NOT an itemised
    transaction history. A risk analyst needs the customer's risk *pattern*
    (how often they fail, what the model treats as their baseline), not a
    browsable ledger of every payment they've made.
    """
    customer_id: str
    total_events: int
    successful: int
    failed: int
    success_rate: float
    flagged_count: int                       # decisions routed to VERIFY / HOLD
    amount_at_risk: float
    history_good: bool
    typical_amount: Optional[float] = None
    usual_device: Optional[str] = None
    usual_payment_method: Optional[str] = None
    recent_failed_streak: int = 0
    prior_event_count: int = 0
    decisions_by_action: Dict[str, int] = {}


class AssessRequest(BaseModel):
    """A payment *about to happen* — the caller wants a verdict before it moves.

    This is the integration surface: a checkout, a PSP, or a Razorpay webhook
    posts the attempt here and gets back an action (and why) synchronously.
    """
    customer_id: str
    amount: float
    payment_method: str
    transaction_id: Optional[str] = None     # generated if the caller doesn't supply one
    merchant_id: Optional[str] = None
    bank: Optional[str] = None
    device_id: Optional[str] = None
    event_time: Optional[datetime] = None


class AssessResponse(BaseModel):
    transaction_id: str
    decision: str                            # APPROVE | RETRY | OFFER_ALTERNATIVE | VERIFY | HOLD
    safe: bool                               # APPROVE only — a convenience flag for callers
    risk_score: float
    recommended_action: Optional[str] = None
    explanation: Optional[str] = None
    signals: List[str] = []
    model_name: Optional[str] = None
    decision_id: int
