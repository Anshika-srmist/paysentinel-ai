from datetime import datetime
from typing import Any, Dict, List, Literal, Optional
from pydantic import BaseModel, ConfigDict, Field

PAYMENT_METHODS = ("UPI", "CARD", "NETBANKING", "WALLET")


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
    """The risk engine's output for one event."""
    id: int
    event_id: int
    risk_score: float                        # the composite risk score
    ml_risk: Optional[float] = None
    behavioral_risk: Optional[float] = None
    network_risk: Optional[float] = None
    rule_severity: Optional[str] = None
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
    merchant_id: Optional[str] = None
    payment_method: Optional[str] = None
    device_id: Optional[str] = None
    amount: float
    status: str
    risk_score: float                        # composite
    ml_risk: Optional[float] = None
    network_risk: Optional[float] = None
    failure_category: Optional[str] = None
    decision: str
    recovery_probability: Optional[float] = None
    created_at: datetime
    event_time: datetime


class DecisionDetail(BaseModel):
    """Full payload for the Investigation page."""
    event: PaymentEventOut
    decision: RiskDecisionOut
    recommended_action: Optional[str] = None
    signals: List[str] = []
    features: Dict[str, Any] = {}
    behavioral: Dict[str, Any] = {}          # {behavioral_risk, signals[], weights}
    network: Dict[str, Any] = {}             # {network_risk, signals[], conclusion, ...}
    explanation_sections: Dict[str, Any] = {}
    audit: List[Dict[str, Any]] = []
    risk_breakdown: Dict[str, Any] = {}      # ml / behavioral / network / rule_severity / composite


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
    Validated so garbage input is rejected rather than silently "working":
    a real amount, a known payment method, sane id lengths.
    """
    customer_id: str = Field(min_length=2, max_length=40, pattern=r"^[A-Za-z0-9_\-]+$")
    amount: float = Field(gt=0, le=10_000_000)
    payment_method: Literal["UPI", "CARD", "NETBANKING", "WALLET"]
    transaction_id: Optional[str] = None     # generated if the caller doesn't supply one
    merchant_id: Optional[str] = Field(default=None, max_length=40)
    bank: Optional[str] = Field(default=None, max_length=50)
    device_id: Optional[str] = Field(default=None, max_length=40, pattern=r"^[A-Za-z0-9_\-]*$")
    event_time: Optional[datetime] = None


class CustomerSummary(BaseModel):
    """One row for the 'pick a real customer' list — aggregate only."""
    customer_id: str
    total_events: int
    typical_amount: Optional[float] = None
    usual_device: Optional[str] = None
    usual_payment_method: Optional[str] = None
    history_good: bool = False
    last_seen: datetime


class AssessResponse(BaseModel):
    transaction_id: str
    decision: str                            # APPROVE | RETRY | OFFER_ALTERNATIVE | VERIFY | HOLD
    safe: bool                               # APPROVE only — a convenience flag for callers
    composite_risk: float
    ml_risk: Optional[float] = None
    behavioral_risk: Optional[float] = None
    network_risk: Optional[float] = None
    rule_severity: Optional[str] = None
    recommended_action: Optional[str] = None
    explanation: Optional[str] = None
    explanation_sections: Dict[str, Any] = {}
    signals: List[str] = []
    network_conclusion: Optional[str] = None
    model_name: Optional[str] = None
    decision_id: int
