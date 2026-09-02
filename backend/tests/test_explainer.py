import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.engine.decision_engine import Decision
from app.engine.explainer import ExplanationContext, explain
from app.engine.failure_classifier import FailureCategory


def _ctx(**overrides) -> ExplanationContext:
    base = dict(
        transaction_id="TXN_ABC123",
        amount=4200.0,
        status="FAILED",
        risk_score=0.42,
        model_name="Random Forest",
        failure_category=FailureCategory.PAYMENT_METHOD,
        decision=Decision.VERIFY,
        recovery_probability=0.55,
        customer_history_good=True,
        signals=["Amount is 4.0x this customer's typical spend"],
    )
    base.update(overrides)
    return ExplanationContext(**base)


def test_explain_falls_back_to_template_when_llm_disabled(monkeypatch):
    monkeypatch.delenv("PAYSENTINEL_USE_LLM", raising=False)
    text, source = explain(_ctx())
    assert source == "template"
    assert text and text[0].isupper()


def test_template_mentions_the_triggered_signal():
    text, _ = explain(_ctx())
    assert "typical spend" in text


def test_template_covers_every_decision():
    for decision in Decision:
        text, source = explain(_ctx(decision=decision))
        assert source == "template"
        assert len(text) > 10


def test_successful_payment_explanation_has_no_recovery_line():
    text, _ = explain(
        _ctx(
            status="SUCCESS",
            failure_category=FailureCategory.NONE,
            decision=Decision.APPROVE,
            recovery_probability=None,
            signals=[],
        )
    )
    assert "recovery" not in text.lower()


def test_prompt_block_is_structured_and_complete():
    block = _ctx().as_prompt_block()
    for key in ("transaction_id:", "risk_score:", "decision:", "triggered_signals:"):
        assert key in block
