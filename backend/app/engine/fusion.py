"""
Risk fusion.

Combines the four independent signals into one **Composite Risk Score**.
This is a risk *indicator*, not a calibrated probability — the weighting
below is a fixed, documented blend, not a statistical model.

    composite = 0.45·ML  +  0.20·behavioural  +  0.35·network
    then raised to a floor set by the rule-severity tag (never lowered)

`rule_severity` is a qualitative tag from deterministic checks (failure
reason, failure category, hard velocity/failure thresholds, any CRITICAL
network signal). It exists so a known-bad pattern can't be averaged away
by two calm signals.
"""
from app.engine.failure_classifier import FailureCategory

BLEND = {"ml": 0.45, "behavioral": 0.20, "network": 0.35}

# rule_severity -> minimum composite it guarantees. CRITICAL sits just
# above the 0.90 HOLD threshold so a corroborated critical pattern is held.
SEVERITY_FLOOR = {"CRITICAL": 0.92, "HIGH": 0.66, "MEDIUM": 0.0, "LOW": 0.0}

_CRITICAL_FAILURE_REASONS = {"SUSPECTED_FRAUD"}
_HIGH_FAILURE_REASONS = {"MULTIPLE_FAILED_ATTEMPTS"}


def rule_severity(
    failure_category: FailureCategory,
    failure_reason: str | None,
    recent_failed_count: int,
    network_signals: list[dict],
) -> str:
    kinds = {s.get("signal") for s in network_signals}
    crit_net = any(s.get("severity") == "critical" for s in network_signals)
    corroborated = len(kinds) >= 2 or {"Transaction velocity", "Amount similarity"} & kinds

    if failure_reason in _CRITICAL_FAILURE_REASONS:
        return "CRITICAL"
    # a critical network signal only mandates a hold when it's corroborated
    # by a second detector — one shared device alone is not enough
    if crit_net and corroborated:
        return "CRITICAL"
    if failure_reason in _HIGH_FAILURE_REASONS:
        return "HIGH"
    if failure_category == FailureCategory.SUSPICIOUS:
        return "HIGH"
    if recent_failed_count >= 4:
        return "HIGH"
    if crit_net or (any(s.get("severity") == "high" for s in network_signals) and corroborated):
        return "HIGH"
    return "LOW"


def fuse(ml_risk: float, behavioral_risk: float, network_risk: float, severity: str) -> float:
    blended = BLEND["ml"] * ml_risk + BLEND["behavioral"] * behavioral_risk + BLEND["network"] * network_risk
    composite = max(blended, SEVERITY_FLOOR.get(severity, 0.0))
    return round(min(1.0, composite), 4)
