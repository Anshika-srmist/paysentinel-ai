# PaySentinel

### Adaptive Payment Risk & Recovery Engine

**Razorpay AI Buildathon 2026 — AI Risk Manager**

> **Live:** dashboard <https://paysentinel-ai.vercel.app> · API <https://paysentinel-ai.onrender.com>
> Synthetic transaction environment. Prototype / demonstration — not connected to real Razorpay data or real money.

Most fraud tools answer *"is this transaction fraudulent?"* PaySentinel answers a
harder set of questions for every payment attempt, in real time:

**What happened? · Why is it risky? · Is the risk isolated or part of a larger
network? · What action should be taken? · Why? · What is the financial impact?**

It combines transaction-level ML, behavioural signals and graph-based network
analysis into one **composite risk score**, runs that through a **deterministic
policy engine** (the model recommends; the policy decides), explains every
decision from structured evidence, records an **audit trail**, and measures the
**decision economics** — because catching fraud at the cost of declining good
customers is not a win.

---

## 1. Problem

Payment fraud detection is hard for reasons a plain classifier ignores:

- **Extreme class imbalance** — fraud is a low single-digit percent of traffic,
  so *accuracy* is meaningless (predict "not fraud" always → ~86% here).
- **False positives are expensive** — a wrongly declined payment loses the sale
  *and* the customer's trust. The right objective is business impact, not raw
  recall.
- **Fraud is coordinated** — rings share devices and instruments and move fast.
  A per-transaction model that scores each attempt in isolation misses the
  pattern.
- **"Because the model said so" is not acceptable** in a payments context —
  every decision needs a traceable reason and a human in the loop for the
  serious ones.

## 2. Architecture

```
 Payment event
      ↓
 Feature engineering        (amount ratio, device/method/merchant novelty, failure streak, hour)
      ↓
 ┌───────────────────────┐  ┌────────────────────┐  ┌──────────────────┐
 │ Transaction ML model  │  │ Behavioural signals│  │ Network analysis │
 │ Random Forest         │  │ scored + evidenced │  │ NetworkX detectors│
 └───────────┬───────────┘  └─────────┬──────────┘  └────────┬─────────┘
             └──────────────┬─────────┴───────────────┬──────┘
                    Risk fusion  →  Composite Risk Score
                            ↓
                    Deterministic policy engine
                            ↓
                    Decision  (APPROVE / RETRY / OFFER_ALTERNATIVE / VERIFY / HOLD)
                            ↓
              Structured explanation  +  Audit trail
                            ↓
                 Outcome / feedback  →  Analytics · Decision economics
```

Frontend: React (Vite), a hand-built design system (light/dark), polling-based
live feed. Backend: FastAPI + SQLite. ML: scikit-learn. Graph: NetworkX (no
GNN — explainable detectors). Deploy: Vercel + Render.

## 3. ML approach — real held-out evaluation

`ml/train.py` runs a bake-off — a randomised-search-tuned **Random Forest**,
**XGBoost**, **LightGBM**, and a Logistic Regression baseline. Everything is
**time-ordered**: the data is sorted by event time, the model is selected by
**5-fold `TimeSeriesSplit` CV** on the earlier window, and the confusion matrix
and threshold sweep come from the **most recent 20%, held out by time**.
Calibration is fit on an in-between slice. Fraud patterns drift and features
look backward in time, so a random split leaks the future into the test set;
this doesn't. Imbalance is handled with `class_weight='balanced'` (or
`scale_pos_weight` for XGBoost). Results go to `ml/metrics.json`.

| model (time-ordered CV) | PR-AUC | recall | FPR |
|---|---|---|---|
| Logistic Regression (baseline) | 0.883 ± 0.022 | 0.870 | 4.8% |
| **Random Forest (tuned, selected)** | **0.894 ± 0.020** | 0.856 | **0.7%** |
| XGBoost | 0.885 ± 0.040 | 0.842 | 0.8% |
| LightGBM | 0.884 ± 0.042 | 0.845 | 0.9% |

**Random Forest is selected** — it holds up best under distribution shift
across time folds (the boosted models have 2× the fold-to-fold spread) and has
by far the lowest false-positive rate. Held-out on the most recent window:
P 0.93 · R 0.81 · PR-AUC 0.87 · FPR 1.1%; confusion matrix TP 401 · FP 28 ·
FN 95 · TN 2552. Recall is lower here than under a random split — that's the
temporal eval doing its job: a model trained only on the past lags the newest
fraud, and the threshold sweep shows where to trade that back.

**Leakage check.** The same model under a random shuffled split scores PR-AUC
**0.887** vs. the time-ordered **0.894** — a −0.007 gap, i.e. the evaluation
isn't borrowing information from the future. (A large positive gap would mean it
was.)

**Calibration.** Isotonic and sigmoid are both fit on the calibration slice and
the one with the lower test-window Brier is shipped (sigmoid, here — it's
steadier on a smaller, drifting calibration set). `CalibratedClassifierCV` over
a frozen base keeps inference at 1× cost. Brier **0.052 → 0.045** on the
held-out window. The *composite* risk score fuses ML + behavioural + network +
rule severity and is still a risk **indicator**, not a probability; only its ML
component is calibrated.

**Dataset & features.** `ml/generate_training_data.py` builds ~15k rows as
**per-customer timelines** over a simulated window, then computes the model
features from each event's position in its timeline — so velocity, recency,
failure-ratio and device-sharing carry real signal. Fraud is injected as
**archetypes**: card testing (tight burst of tiny transactions), account
takeover (new device + method + amount spike after a clean history), bust-out (a
spending ramp — only the escalated tail is labelled), and coordinated rings
(fresh accounts sharing a device). Plus deliberate hard negatives (legit
big-ticket buys, a genuine new device, a flaky-bank retry run) and ~2% symmetric
label noise. The 14 features are shared by training and serving via
`app/engine/features_common.py` so they can't drift; top importances are
absolute amount, time-since-last-payment, amount-vs-typical and amount z-score.

## 4. Behavioural signals

`app/engine/behavioral.py` scores each attempt against the customer's own
history and emits `LOW / MEDIUM / HIGH / CRITICAL` signals with **evidence** and
a **contribution weight** — phrased for an operator, not raw feature names:

> *Amount deviation — HIGH — "₹48,920 vs customer's typical ₹7,400 (6.6×)"*

Covers amount deviation, velocity, new device / method / merchant, unusual hour,
recent failure streak. Behavioural risk = a documented weighted sum.

## 5. Network analysis

`app/engine/network.py` builds a NetworkX graph (customer / device / merchant
nodes) and runs **explainable detectors** over the neighbourhood of each
transaction — no GNN, every score traces to a countable fact:

- **shared device** — accounts transacting from one device
- **transaction velocity** — burst on a device or customer
- **merchant concentration** — linked accounts hitting one merchant
- **amount similarity** — near-identical amounts across the cluster
- **dense cluster** — a tight multi-account group with high activity

Network risk = a documented weighted sum. A device shared by 2–3 accounts is
*not* alone a strong signal (families, shared machines) — it needs corroboration
by velocity or amount-similarity. Clusters, entity detail and the graph are
exposed at `/network/*` and rendered on the **Network** page.

## 6. Risk fusion + policy

```
composite = 0.45·ML  +  0.20·behavioural  +  0.35·network
then raised to a floor by rule severity  (CRITICAL ≥ 0.92, HIGH ≥ 0.66)
```

Labelled **"Composite Risk Score"** — a risk indicator with a documented
blend, **not** a calibrated probability. The rule-severity floor stops a
known-bad pattern from being averaged away by two calm signals.

The **deterministic policy engine** (`decision_engine.py`) takes the composite
and returns the action:

| condition | decision |
|---|---|
| composite > 0.90 | **HOLD** (block + case for review) |
| temporary failure AND composite < 0.30 | **RETRY** (bounded) |
| payment-method failure AND good history | **OFFER_ALTERNATIVE** |
| 0.30 ≤ composite ≤ 0.90 | **VERIFY** (step-up) |
| otherwise | **APPROVE** |

*The model recommends a score. The policy decides the permitted action.* Every
evaluation shows which rule fired.

## 7. Explainability

Every decision produces a **structured** explanation from the evidence the
engine actually generated — never invented:

- *What the model saw* · *What the network saw* · *Why this action was chosen
  (which policy rule)* · *What an operator should do next*

If an LLM is enabled (`PAYSENTINEL_USE_LLM=1`) it only *rewrites the one-line
summary*, grounded in the same evidence. If it's off or errors, the
deterministic summary stands. The user always sees "Decision explanation".

## 8. Audit trail + recovery

Every decision persists a timeline: *payment received → features → ML scored →
network analysed → composite → policy rule → decision → case created*. Shown on
Investigation.

Failed low-risk payments get a **bounded recovery plan** — a `RETRY` carries a
reason, an expected recovery probability, and a stopping rule (stop on success,
risk increase, or the retry limit).

## 9. Financial impact — decision economics

The Analytics page turns the held-out confusion matrix into money, under
**clearly labelled simulation assumptions** you can change (avg. fraud loss ₹,
avg. false-decline cost ₹):

```
  +  fraud loss prevented      = TP × fraud_loss
  −  false-decline cost        = FP × decline_cost
  =  net impact vs. no detection
```

Shown separately, **not** part of the net: the model's **coverage gap** —
`FN × fraud_loss`, the fraud that scored below threshold and got through. It's
what a better model would recover, not a cost the system introduces.

The point: the system optimises *business impact*, not blind fraud detection.
These figures are simulated and never represented as real Razorpay data.

## 10. Integration surface

- **`POST /assess`** — score a payment *before it settles*, get
  `{decision, composite_risk, ml/behavioural/network, explanation}`
  synchronously. A checkout or PSP calls this and acts on the verdict.
- **`POST /webhooks/razorpay`** — ingest real Razorpay (test-mode)
  `payment.captured` / `payment.failed` webhooks; HMAC-verified, idempotent.
- **`POST /decisions/{id}/feedback`** — an analyst records the true outcome
  (`fraud` / `legitimate`); `GET /feedback/summary` returns labelled accuracy.
- **`GET /ops/metrics`** — request volume, p50/p95 latency per route, and the
  decision mix since boot.
- **`frontend/public/checkout.html`** — a working Razorpay test-mode checkout.
  Full loop: [`docs/RAZORPAY_TESTING.md`](docs/RAZORPAY_TESTING.md).

## 11. Limitations & responsible AI

- **Synthetic data only.** No real customer data, no payment credentials stored,
  no autonomous movement of real money.
- The composite score is a **risk indicator, not a calibrated probability**.
- Financial impact figures are **simulations** with labelled assumptions.
- The customer view shows **aggregate risk signals only** — not a browsable
  per-customer transaction ledger.
- **Defensive only.** High-risk decisions (`HOLD` / `VERIFY`) require human
  review; deterministic policy guardrails sit above the ML; every decision is
  auditable.
- Analyst feedback (`POST /decisions/{id}/feedback`, and a control on the
  Investigation page) records what a transaction actually turned out to be.
  `GET /feedback/summary` aggregates it into a labelled-accuracy view — a
  confusion matrix over the reviewed subset. It is **not** wired to retraining;
  the model does not learn online.

## 12. Setup

```bash
# backend
cd backend
pip install -r requirements.txt
python ml/generate_training_data.py && python ml/train.py   # writes metrics.json + saved_model.pkl
uvicorn app.main:app --reload                               # :8000, seeds ~140 events incl. the coordinated ring

# frontend
cd frontend
npm install
npm run dev                                                 # :5173, proxies /api -> :8000

# tests
cd backend && PYTHONPATH=. pytest tests/ -q                 # 76 pass
```

## 13. API

`POST /assess` · `POST /payments` · `GET /decisions` · `GET /decisions/{id}` ·
`GET /transactions/{id}/network` · `GET /audit/{txn}` ·
`GET /model/metrics` · `GET /analytics` · `GET /analytics/economics` ·
`GET /network/graph` · `GET /network/clusters` · `GET /network/entity/{kind}/{ref}` ·
`GET /policy` · `GET /customers/{id}` · `GET /stats/summary` ·
`POST /webhooks/razorpay` · `GET /health`

Auto-generated docs at `/docs`.

## 14. Demo

Navigation: **Overview → Live Stream → Investigation → Network → Analytics →
Policy**. Deterministic seeded data (`seed=42`) includes a **coordinated ring**
— 4 accounts on `DEVICE_RING`, 13 near-identical payments in ~6 minutes → network
risk lights up → composite 0.92 → **HOLD**. That is the hero case: open a ring
transaction in Investigation, follow the risk breakdown and network exposure to
the Network page, see the cluster, return for the explanation and audit trail,
then Analytics for precision / recall / false-positive cost.

Full architecture rationale: [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md).
Deploy runbook: [`DEPLOY.md`](DEPLOY.md).
