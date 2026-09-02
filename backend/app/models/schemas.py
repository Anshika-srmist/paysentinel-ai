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
