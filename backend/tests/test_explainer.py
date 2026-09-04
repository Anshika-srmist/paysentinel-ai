import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.engine.decision_engine import Decision
from app.engine.explainer import ExplanationContext, explain
from app.engine.failure_classifier import FailureCategory


def _ctx(**overrides) -> ExplanationContext:
    base = dict(
        transaction_id="TXN_ABC123",
        amount=48920.0,
        status="PENDING",
        decision=Decision.HOLD,
        composite_risk=0.91,
        ml_risk=0.72,
        behavioral_risk=0.81,
        network_risk=0.93,
        rule_severity="CRITICAL",
        failure_category=FailureCategory.NONE,
        recovery_probability=None,
        policy_rule="composite_risk > 0.9",
        network_conclusion="Coordinated activity across 4 accounts and 1 shared device.",
        behavioral_signals=[
            {"signal": "Amount deviation", "severity": "high",
             "evidence": "₹48,920 vs customer's typical ₹7,400 (6.6x)", "contribution": 0.3},
        ],
        network_signals=[
            {"signal": "Shared device", "severity": "high",
             "evidence": "4 customer accounts have transacted from DEVICE_14", "contribution": 0.34},
        ],
    )
    base.update(overrides)
    return ExplanationContext(**base)


def test_explain_returns_structured_sections_without_an_llm(monkeypatch):
    monkeypatch.delenv("PAYSENTINEL_USE_LLM", raising=False)
    sections, source = explain(_ctx())
    assert source == "structured"
    for key in ("summary", "what_the_model_saw", "what_the_network_saw",
                "why_this_action", "what_should_happen_next"):
        assert sections[key] and isinstance(sections[key], str)


def test_sections_are_grounded_in_the_supplied_evidence():
    sections, _ = explain(_ctx())
    assert "48,920" in sections["summary"] or "6.6x" in sections["summary"].lower()
    assert "shared device" in sections["what_the_network_saw"].lower() or "coordinated" in sections["what_the_network_saw"].lower()
    assert "0.91" in sections["why_this_action"]


def test_every_decision_produces_sections():
    for decision in Decision:
        sections, source = explain(_ctx(decision=decision, composite_risk=0.2, rule_severity="LOW",
                                        behavioral_signals=[], network_signals=[], network_conclusion=None))
        assert source == "structured"
        assert len(sections["why_this_action"]) > 10


def test_clean_payment_has_no_network_or_behavioural_noise():
    sections, _ = explain(_ctx(
        decision=Decision.APPROVE, composite_risk=0.06, rule_severity="LOW",
        behavioral_signals=[], network_signals=[], network_conclusion=None,
    ))
    assert "no significant connected activity" in sections["what_the_network_saw"].lower()
    assert "no behavioural anomalies" in sections["what_the_model_saw"].lower()


def test_prompt_block_is_structured():
    block = _ctx().as_prompt_block()
    for key in ("decision:", "composite_risk:", "rule_severity:", "why_this_action:"):
        assert key in block
