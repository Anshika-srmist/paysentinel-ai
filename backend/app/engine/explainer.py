"""
AI explainability layer — the single deliberate LLM touchpoint.

Given the structured output of the risk engine (score, triggered
signals, failure category, decision, recovery probability), produce a
1–2 sentence plain-English reason a payments-ops person could read at a
glance. This is what makes PaySentinel an *AI* system rather than an
ML + rules app; it is intentionally a small, cheap call, not a chatbot.

Two design decisions worth knowing:

1. There is always a deterministic template explanation. The LLM is an
   *enhancement*, not a dependency — if it is disabled, unconfigured,
   rate-limited, or times out, the system still produces a readable
   reason and never blocks ingestion. `explain()` returns which source
   was used so the dashboard/pitch can show it.

2. The LLM is off by default (`PAYSENTINEL_USE_LLM=1` to enable). Tests
   and offline demos run entirely on the template path. When enabled it
   uses the Anthropic API; the model is configurable and the call is
   made with a short timeout and a tight token budget.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from typing import List, Literal, Tuple

from app.engine.decision_engine import Decision
from app.engine.failure_classifier import FailureCategory

try:  # optional dependency — only needed when the LLM path is enabled
    import anthropic
except ImportError:  # pragma: no cover - exercised only in envs without the SDK
    anthropic = None

ExplanationSource = Literal["llm", "template"]

_DEFAULT_MODEL = "claude-opus-5"
_LLM_TIMEOUT_SECONDS = 8.0
_LLM_MAX_TOKENS = 200

_SYSTEM_PROMPT = (
    "You explain automated payment-risk decisions to a payments operations "
    "analyst. Given a structured summary of one payment, write 1-2 short, "
    "factual sentences stating why the system chose this action. Reference "
    "the concrete signals provided. No preamble, no markdown, no advice "
    "beyond the chosen action, no invented details."
)


@dataclass
class ExplanationContext:
    transaction_id: str
    amount: float
    status: str                       # SUCCESS | FAILED
    risk_score: float
    model_name: str
    failure_category: FailureCategory
    decision: Decision
    recovery_probability: float | None
    customer_history_good: bool
    signals: List[str]

    def as_prompt_block(self) -> str:
        lines = [
            f"transaction_id: {self.transaction_id}",
            f"amount: {self.amount}",
            f"status: {self.status}",
            f"risk_score: {self.risk_score:.4f} (0=safe, 1=high risk; scored by {self.model_name})",
            f"failure_category: {self.failure_category.value}",
            f"decision: {self.decision.value}",
            f"customer_history_good: {self.customer_history_good}",
        ]
        if self.recovery_probability is not None:
            lines.append(f"recovery_probability: {self.recovery_probability:.2f}")
        if self.signals:
            lines.append("triggered_signals:")
            lines.extend(f"  - {s}" for s in self.signals)
        else:
            lines.append("triggered_signals: none")
        return "\n".join(lines)


# --- Template path (always available) ------------------------------------

_DECISION_LEAD = {
    Decision.APPROVE: "Approved automatically",
    Decision.RETRY: "Safe to retry automatically",
    Decision.OFFER_ALTERNATIVE: "Recommend offering an alternative payment method",
    Decision.VERIFY: "Routed for step-up verification",
    Decision.HOLD: "Held for manual review",
}


def _template_explanation(ctx: ExplanationContext) -> str:
    lead = _DECISION_LEAD[ctx.decision]
    score_phrase = f"risk score {ctx.risk_score:.2f}"

    if ctx.decision == Decision.HOLD:
        first = f"{lead}: {score_phrase} is above the {0.90:.2f} block threshold."
    elif ctx.decision == Decision.VERIFY:
        first = f"{lead}: {score_phrase} is in the elevated range."
    elif ctx.decision == Decision.RETRY:
        first = f"{lead}: {ctx.failure_category.value} failure with a low {score_phrase}."
    elif ctx.decision == Decision.OFFER_ALTERNATIVE:
        first = (
            f"{lead}: the payment method failed for a customer with a good "
            f"history and a low {score_phrase}."
        )
    else:  # APPROVE
        if ctx.signals:
            first = f"{lead}: {score_phrase} is below the review threshold despite the notes below."
        else:
            first = f"{lead}: {score_phrase} is low and no risk signals fired."

    parts = [first]
    if ctx.signals:
        shown = "; ".join(ctx.signals[:2])
        parts.append(f"Key signals: {shown}.")
    if ctx.recovery_probability is not None:
        parts.append(f"Estimated recovery probability {ctx.recovery_probability:.0%}.")
    return " ".join(parts)


# --- LLM path (optional) ------------------------------------------------

def _llm_enabled() -> bool:
    return os.getenv("PAYSENTINEL_USE_LLM", "0") == "1" and anthropic is not None


def _llm_explanation(ctx: ExplanationContext) -> str | None:
    """Returns an LLM-written explanation, or None on any failure (caller falls back)."""
    model = os.getenv("PAYSENTINEL_LLM_MODEL", _DEFAULT_MODEL)
    try:
        client = anthropic.Anthropic()  # resolves key/profile from the environment
        response = client.with_options(timeout=_LLM_TIMEOUT_SECONDS).messages.create(
            model=model,
            max_tokens=_LLM_MAX_TOKENS,
            system=_SYSTEM_PROMPT,
            messages=[{"role": "user", "content": ctx.as_prompt_block()}],
        )
        text = "".join(b.text for b in response.content if b.type == "text").strip()
        return text or None
    except Exception as exc:  # noqa: BLE001 - explainer must never break ingestion
        print(f"[explainer] LLM call failed, using template fallback: {exc}")
        return None


# --- Public entry point ------------------------------------------------

def explain(ctx: ExplanationContext) -> Tuple[str, ExplanationSource]:
    """
    Produce a plain-English reason for the decision. Uses the LLM when it
    is enabled and succeeds, otherwise the deterministic template. Always
    returns a non-empty string plus the source that produced it.
    """
    if _llm_enabled():
        llm_text = _llm_explanation(ctx)
        if llm_text:
            return llm_text, "llm"
    return _template_explanation(ctx), "template"
