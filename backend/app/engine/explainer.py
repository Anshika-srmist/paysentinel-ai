"""
Decision explanation.

Every decision gets a **structured** explanation, assembled deterministically
from the evidence the engine actually produced — model output, behavioural
signals, network conclusion, the policy rule that fired. It answers, in order:

    - what the model saw
    - what the network saw
    - why this action was chosen
    - what an operator should do next

If an LLM is enabled (`PAYSENTINEL_USE_LLM=1`) it *rewrites the one-line
summary* into cleaner prose, grounded only in the same evidence — it is never
allowed to invent facts, and it never replaces the structured sections. If it
is off, unconfigured, or errors, the deterministic summary stands. The user
always just sees "Decision explanation"; `source` (`llm` / `structured`) is
internal.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import List, Literal, Tuple

from app.engine.decision_engine import Decision
from app.engine.failure_classifier import FailureCategory

try:  # optional — only needed when the LLM path is enabled
    import anthropic
except ImportError:  # pragma: no cover
    anthropic = None

ExplanationSource = Literal["llm", "structured"]

_DEFAULT_MODEL = "claude-opus-5"
_LLM_TIMEOUT_SECONDS = 8.0
_LLM_MAX_TOKENS = 180

_SYSTEM_PROMPT = (
    "You rewrite a one-line rationale for an automated payment-risk decision, "
    "for a payments operations analyst. Use ONLY the facts in the structured "
    "summary provided. One or two plain sentences, no preamble, no markdown, "
    "no invented details, no advice beyond the chosen action."
)

_DECISION_LEAD = {
    Decision.APPROVE: "Approved",
    Decision.RETRY: "Sent for automatic retry",
    Decision.OFFER_ALTERNATIVE: "Recommend an alternative payment method",
    Decision.VERIFY: "Routed for step-up verification",
    Decision.HOLD: "Held for analyst review",
}

_NEXT_STEP = {
    Decision.APPROVE: "No action — the payment can proceed.",
    Decision.RETRY: "Retry automatically (bounded); stop on success, risk increase, or the retry limit.",
    Decision.OFFER_ALTERNATIVE: "Prompt the customer to choose a different payment method.",
    Decision.VERIFY: "Require a step-up check (OTP / 3-D Secure) before the payment settles.",
    Decision.HOLD: "Block the payment and open a case for analyst review; review linked accounts if a cluster is flagged.",
}


@dataclass
class ExplanationContext:
    transaction_id: str
    amount: float
    status: str
    decision: Decision
    composite_risk: float
    ml_risk: float
    behavioral_risk: float
    network_risk: float
    rule_severity: str
    failure_category: FailureCategory
    recovery_probability: float | None
    policy_rule: str | None = None                 # which rule fired, e.g. "risk_score > 0.9"
    network_conclusion: str | None = None
    behavioral_signals: List[dict] = field(default_factory=list)
    network_signals: List[dict] = field(default_factory=list)
    model_name: str = "risk model"

    # ---- deterministic sections ----
    def _model_saw(self) -> str:
        beh = [s for s in self.behavioral_signals]
        if not beh:
            return (
                f"The transaction model scored {self.ml_risk:.2f} and no behavioural "
                f"anomalies were detected for this customer."
            )
        top = "; ".join(f"{s['signal'].lower()} ({s['evidence']})" for s in beh[:3])
        return (
            f"The transaction model scored {self.ml_risk:.2f}. Behavioural signals: {top}."
        )

    def _network_saw(self) -> str:
        if not self.network_signals:
            return "Network analysis found no significant connected activity."
        return self.network_conclusion or (
            f"Network risk {self.network_risk:.2f} — "
            + "; ".join(s["signal"].lower() for s in self.network_signals[:3])
            + "."
        )

    def _why_action(self) -> str:
        lead = _DECISION_LEAD[self.decision]
        if self.decision == Decision.HOLD:
            reason = (
                f"composite risk {self.composite_risk:.2f} is above the 0.90 block threshold"
                if self.composite_risk > 0.9
                else f"the {self.rule_severity.lower()}-severity rule mandates a hold"
            )
        elif self.decision == Decision.VERIFY:
            reason = f"composite risk {self.composite_risk:.2f} is in the 0.30–0.90 review band"
        elif self.decision == Decision.RETRY:
            reason = f"a {self.failure_category.value} failure with low composite risk {self.composite_risk:.2f}"
        elif self.decision == Decision.OFFER_ALTERNATIVE:
            reason = f"a payment-method failure for a trusted customer at low risk {self.composite_risk:.2f}"
        else:
            reason = f"composite risk {self.composite_risk:.2f} is low with no blocking condition"
        rule = f" (policy: {self.policy_rule})" if self.policy_rule else ""
        return f"{lead} because {reason}{rule}."

    def sections(self) -> dict:
        return {
            "summary": self._summary(),
            "what_the_model_saw": self._model_saw(),
            "what_the_network_saw": self._network_saw(),
            "why_this_action": self._why_action(),
            "what_should_happen_next": _NEXT_STEP[self.decision],
        }

    def _summary(self) -> str:
        bits = []
        strong_beh = [s for s in self.behavioral_signals if s["severity"] in ("high", "critical")]
        if strong_beh:
            bits.append(strong_beh[0]["evidence"].lower())
        if self.network_signals:
            bits.append((self.network_signals[0]["evidence"]).lower())
        detail = "; ".join(bits)
        lead = _DECISION_LEAD[self.decision]
        if detail:
            return f"{lead}: composite risk {self.composite_risk:.2f} — {detail}."
        return f"{lead}: composite risk {self.composite_risk:.2f}."

    def as_prompt_block(self) -> str:
        s = self.sections()
        return (
            f"decision: {self.decision.value}\n"
            f"composite_risk: {self.composite_risk:.2f} "
            f"(model {self.ml_risk:.2f}, behavioural {self.behavioral_risk:.2f}, network {self.network_risk:.2f})\n"
            f"rule_severity: {self.rule_severity}\n"
            f"what_the_model_saw: {s['what_the_model_saw']}\n"
            f"what_the_network_saw: {s['what_the_network_saw']}\n"
            f"why_this_action: {s['why_this_action']}"
        )


def _llm_enabled() -> bool:
    return os.getenv("PAYSENTINEL_USE_LLM", "0") == "1" and anthropic is not None


def _llm_summary(ctx: ExplanationContext) -> str | None:
    model = os.getenv("PAYSENTINEL_LLM_MODEL", _DEFAULT_MODEL)
    try:
        client = anthropic.Anthropic()
        resp = client.with_options(timeout=_LLM_TIMEOUT_SECONDS).messages.create(
            model=model,
            max_tokens=_LLM_MAX_TOKENS,
            system=_SYSTEM_PROMPT,
            messages=[{"role": "user", "content": ctx.as_prompt_block()}],
        )
        text = "".join(b.text for b in resp.content if b.type == "text").strip()
        return text or None
    except Exception as exc:  # noqa: BLE001 - must never break ingestion
        print(f"[explainer] LLM unavailable, using structured summary: {exc}")
        return None


def explain(ctx: ExplanationContext) -> Tuple[dict, ExplanationSource]:
    """Return (sections dict, source). `source` is internal only."""
    sections = ctx.sections()
    source: ExplanationSource = "structured"
    if _llm_enabled():
        polished = _llm_summary(ctx)
        if polished:
            sections["summary"] = polished
            source = "llm"
    return sections, source
