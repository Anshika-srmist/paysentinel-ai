# PaySentinel AI
### An Intelligent Payment Risk, Failure Recovery & Decision Engine

**Razorpay AI Buildathon 2026 — Track: AI Risk Manager**

Most systems answer *"what happened to this payment?"* PaySentinel AI answers
*"what should happen next?"* — every payment event is scored for risk,
classified by why it failed (if it did), and resolved into a policy-controlled
decision with a plain-English explanation, instead of a flat success/fail
message.

Full architecture and design rationale: [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md)

---

## Status

- [x] **Day 1** — Payment event simulator (5 scenario types) + FastAPI ingestion + persistence
- [x] **Day 2** — Risk scoring model (Logistic Regression vs. Random Forest, compared on precision/recall/F1/PR-AUC) + rule-based failure classifier
- [x] **Day 3** — Feature extraction from live customer history + deterministic decision engine + recovery-probability heuristic + AI explainability layer (LLM with a template fallback), all wired into ingestion
- [x] **Day 4** — React dashboard (Overview / Live Stream / Investigation), polling-based live feed; deploy config for Vercel
- [ ] **Day 5** — Pitch video, final docs, submission

## Quickstart

```bash
cd backend
pip install -r requirements.txt

# terminal 1 — start the API
uvicorn app.main:app --reload

# terminal 2 — start the simulator (continuous)
python simulator/simulate_payments.py

# or fire a quick batch instead of waiting on the continuous feed
python simulator/simulate_payments.py --count 50
```

```bash
# terminal 3 — the dashboard (proxies /api -> localhost:8000 in dev)
cd frontend
npm install
npm run dev            # http://localhost:5173
```

API docs (auto-generated): http://localhost:8000/docs

Run tests:
```bash
cd backend
PYTHONPATH=. pytest tests/ -v
```

## Risk model

```bash
cd backend
python ml/generate_training_data.py   # generates a labeled synthetic dataset
python ml/train.py                     # trains + compares LogReg vs Random Forest, saves the winner
```

We use a synthetic dataset generated from the same feature logic as the
simulator (not the Kaggle credit-card dataset) so that every feature is
human-readable — `amount_ratio_to_typical`, `is_new_device`, etc. — which
the explainability layer needs to produce a plain-English reason. See
`docs/ARCHITECTURE.md` for the full reasoning, including the class-overlap
noise deliberately added to the generator so the classification task isn't
trivially separable (early versions scored a suspicious, useless 100% —
fixed by making the feature distributions genuinely overlap between normal
and risky behaviour, plus a few percent of symmetric label noise).

Current comparison (held-out 20%, ~14% positive rate — `ml/model_comparison.csv`):

| model | precision | recall | F1 | PR-AUC | ROC-AUC |
|---|---|---|---|---|---|
| Logistic Regression (baseline) | 0.64 | 0.86 | 0.74 | 0.87 | 0.93 |
| **Random Forest** (selected) | **0.90** | **0.87** | **0.88** | **0.89** | 0.93 |

The Random Forest is picked on PR-AUC. It lifts precision from 0.64 → 0.90
at the same recall — it captures interactions between amount ratio, device
change and failure history that the linear model flattens.

## Decision engine & explainability (Day 3)

Every ingested payment now runs through a pipeline before it's stored:

1. **Feature extraction** (`app/engine/feature_extractor.py`) — recomputes the
   Day 2 model features (`amount_ratio_to_typical`, `is_new_device`,
   `recent_failed_count`, …) from the customer's *actual* prior events in the
   database. New customers fall back to neutral values.
2. **Risk score** — the Day 2 model scores the feature row.
3. **Failure category** — the Day 2 rule-based classifier.
4. **Decision** (`app/engine/decision_engine.py`) — a deterministic if/elif
   policy over the score + category → `APPROVE | RETRY | OFFER_ALTERNATIVE |
   VERIFY | HOLD`. The ML model recommends; this policy decides.
5. **Recovery probability** (`app/engine/recovery.py`) — a transparent
   heuristic (base rate per failure category, adjusted by risk and retry
   history), not a second model.
6. **Explanation** (`app/engine/explainer.py`) — one small LLM call turns the
   structured signals into a 1–2 sentence plain-English reason. It's **off by
   default** and always has a deterministic template fallback, so the system
   runs — and tests pass — with no API key. Enable it with
   `PAYSENTINEL_USE_LLM=1` (see `backend/.env.example`).

New endpoints: `GET /decisions` (paginated, `?decision=HOLD` filter),
`GET /decisions/{id}` (full Investigation detail), `GET /health` (DB + model
readiness probe), and `/stats/summary` now reports `high_risk`,
`revenue_at_risk`, and a decision breakdown. `GET /payments` and
`GET /decisions` take `limit` (1–500) + `offset`.

Insight endpoints: `GET /policy` (the decision rules, thresholds, model feature
importances, recovery base rates — everything the "Policy" page shows) and
`GET /customers/{id}` (a customer's **aggregate** risk signals — success rate,
decision mix, and the behavioural baseline the model compares against;
deliberately not an itemised transaction log).

### Integration surface — using PaySentinel *before* a payment moves

Everything above scores a payment that already happened. Two endpoints let a
real payment flow ask *"is this attempt safe?"* up front:

- **`POST /assess`** — a checkout page, a PSP, or any payment flow posts the
  attempt (`customer_id`, `amount`, `payment_method`, optional device/bank) and
  gets back `{ decision, safe, risk_score, explanation, signals }` synchronously.
  `APPROVE` → let it through, `VERIFY` → step-up challenge, `HOLD` → block. The
  attempt is stored as `PENDING` so it also appears in the dashboard.

  ```bash
  curl -X POST https://<api>/assess -H 'content-type: application/json' \
    -d '{"customer_id":"CUST_42","amount":95000,"payment_method":"CARD","device_id":"NEW_DEVICE"}'
  # -> {"decision":"HOLD","safe":false,"risk_score":1.0,"explanation":"Held for manual review: …"}
  ```

  Optional `X-API-Key` gate: set `PAYSENTINEL_API_KEY`.

- **`POST /webhooks/razorpay`** — point a Razorpay (test-mode) webhook here and
  every `payment.captured` / `payment.failed` event is mapped and scored by the
  same pipeline (amount de-paise'd, method/error mapped, idempotent on retry).
  Verifies `X-Razorpay-Signature` when `PAYSENTINEL_RAZORPAY_WEBHOOK_SECRET` is set.

You can't hook into Google Pay / PhonePe internals (closed systems) — but this
is exactly how a PSP or merchant would consume a risk engine.

### Operational scripts

```bash
cd backend
python scripts/backfill_decisions.py            # score events that have no decision yet
python scripts/backfill_decisions.py --rescore  # wipe + re-score everything (after engine changes)
python scripts/loadtest_pipeline.py --count 1000 # pipeline latency / throughput check
```

Measured pipeline throughput is ~10 events/s (≈85 ms/event, dominated by the
single-row Random Forest prediction) — far above the simulator's rate; batch
scoring or a smaller forest is the lever if real-time volume ever matters.

## Dashboard (Day 4)

`frontend/` — Vite + React, no UI framework (a hand-built design system, so it
reads as designed rather than generated). Three pages, all polling the API:

- **Overview** (`/`) — stat tiles (payments, success rate, failed, flagged,
  revenue at risk), a "decisions by action" breakdown, a throughput sparkline,
  and recent activity. Polls every 5s.
- **Live Stream** (`/stream`) — the decision feed, newest first, new rows animate
  in; filter pills per action; each row → Investigation. Polls every 3s.
- **Live Check** (`/check`) — a form that calls `POST /assess` and shows the
  pre-payment verdict live (decision, safe flag, risk meter, explanation).
- **Investigation** (`/investigation/:id`) — the pitch screen: the verdict and
  recommended action, risk-score meter, the **AI explanation** (with an
  LLM/template badge), the triggered signals, the feature snapshot the engine
  scored, and the full payment + decision record. `/investigation` alone lists
  what needs attention (HOLD / VERIFY). The customer id links to →
- **Customer** (`/customers/:id`) — that customer's **aggregate** risk profile:
  success rate, decision mix, and the behavioural baseline the model compares
  against. No itemised transaction history — a risk view, not a ledger.
- **Policy** (`/policy`) — the decision rules as a numbered flow, the model's
  feature importances, and the recovery base rates. This is the "AI recommends,
  a deterministic policy decides" story, made concrete.

Config: dev proxies `/api` → `localhost:8000` (see `vite.config.js`); for a
Vercel deploy set `VITE_API_BASE_URL` to the backend origin (`frontend/.env.example`,
`frontend/vercel.json`).

## Deploy

Backend → **Render** (`backend/render.yaml` blueprint), frontend → **Vercel**
(`frontend/vercel.json`). Render's filesystem is ephemeral, so the backend
re-seeds its SQLite DB on each boot (`app/seed.py`, ~140 scored events;
`PAYSENTINEL_SEED_ON_START=0` to disable). Full step-by-step: [`DEPLOY.md`](DEPLOY.md).

During a demo you can point the simulator at the deployed API to add live
traffic: `python simulator/simulate_payments.py --api https://<your-api>`.

## Project structure

```
paysentinel/
├── DEPLOY.md                 # step-by-step deploy runbook
├── backend/
│   ├── app/
│   │   ├── main.py          # FastAPI app, routes, lifespan (schema + seed)
│   │   ├── seed.py          # first-boot data seeding (ephemeral hosts)
│   │   ├── models/          # ORM models + Pydantic schemas
│   │   ├── engine/          # feature extraction / risk / decision / recovery / explainer
│   │   └── db/               # database setup (SQLite for the MVP)
│   ├── ml/                   # model + anomaly training scripts
│   ├── simulator/            # payment event simulator
│   ├── scripts/              # backfill + load-test utilities
│   ├── tests/
│   ├── render.yaml           # Render blueprint
│   └── Procfile              # Railway / Heroku-style start
└── frontend/
    ├── src/
    │   ├── pages/            # Overview, LiveStream, Investigation(+Index)
    │   ├── components/       # AppShell, StatusChip, RiskMeter, Sparkline, …
    │   ├── hooks/            # usePolling
    │   ├── lib/              # formatting + decision metadata
    │   └── styles/           # design tokens + global css
    └── vercel.json
```

## Why these choices

See [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) for the full reasoning —
short version: FastAPI + SQLite for a zero-friction build under time
pressure, a deterministic policy layer sitting on top of the ML risk score
(so a probabilistic model never makes an uncontrolled financial decision),
and a single deliberate LLM touchpoint for generating human-readable
explanations rather than a full chatbot.

This project shares its core engine with **FinSentinel**, a financial-crime
and transaction-network intelligence extension built afterward for a
separate application. Full extension plan: [`docs/FINSENTINEL_EXTENSION.md`](docs/FINSENTINEL_EXTENSION.md)
