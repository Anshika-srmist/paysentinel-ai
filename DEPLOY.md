# Deploying PaySentinel AI

Two pieces:

| Piece | Host | Root dir | Notes |
|---|---|---|---|
| Backend (FastAPI) | **Render** (free web service) | `backend/` | Ephemeral filesystem — re-seeds its SQLite DB on every boot |
| Frontend (React) | **Vercel** (free) | `frontend/` | Static build; needs the backend URL at build time |

Do the backend first — you need its URL for the frontend.

---

## 1. Backend → Render

### Option A — Blueprint (uses `backend/render.yaml`)

1. Push the repo to GitHub.
2. Render dashboard → **New +** → **Blueprint** → pick this repo.
3. Render reads `backend/render.yaml` and shows one service, `paysentinel-api`. **Apply**.
4. First build takes ~3–5 min (scikit-learn / pandas wheels). When it's live, note the URL, e.g. `https://paysentinel-api.onrender.com`.
5. Check it: open `https://<your-api>.onrender.com/health` → `{"status":"ok", ...}`.

### Option B — Manual web service

New + → **Web Service** → connect the repo, then:

| Field | Value |
|---|---|
| Root Directory | `backend` |
| Runtime | Python 3 |
| Build Command | `pip install -r requirements.txt` |
| Start Command | `uvicorn app.main:app --host 0.0.0.0 --port $PORT` |
| Health Check Path | `/health` |

Environment variables:

| Key | Value | Why |
|---|---|---|
| `PYTHON_VERSION` | `3.12` | matches the tested toolchain |
| `PAYSENTINEL_SEED_ON_START` | `1` | populate the DB on first boot |
| `PAYSENTINEL_SEED_COUNT` | `140` | how many events to seed (lower = faster cold start) |
| `PAYSENTINEL_USE_LLM` | `0` | `1` + `ANTHROPIC_API_KEY` to use real LLM explanations |
| `PAYSENTINEL_CORS_ORIGINS` | *(unset)* | set to your Vercel URL once you have it, to lock CORS |

### Heads-up: free tier sleeps

Render free web services spin down after ~15 min idle and take ~30–60 s to wake
(plus ~15 s to re-seed). Before a live demo, open `/health` once to warm it, or
keep it warm with a free pinger (e.g. cron-job.org hitting `/health` every 10 min).

### Railway instead of Render

Works too: new project from the repo, set **Root Directory** to `backend`, and
Railway picks up `backend/Procfile`. Set the same env vars.

---

## 2. Frontend → Vercel

1. Vercel dashboard → **Add New… → Project** → import the repo.
2. Set **Root Directory** to `frontend`. Framework preset auto-detects as **Vite**
   (`frontend/vercel.json` also pins the build + SPA rewrite).
3. **Environment Variables** → add:

   | Key | Value |
   |---|---|
   | `VITE_API_BASE_URL` | `https://<your-api>.onrender.com` *(no trailing slash)* |

4. **Deploy.** You get a URL like `https://paysentinel.vercel.app`.

> `VITE_*` vars are baked in at build time — if you change `VITE_API_BASE_URL`
> later, redeploy the frontend.

---

## 3. Wire them together

1. In Render, set `PAYSENTINEL_CORS_ORIGINS` to your Vercel URL
   (`https://paysentinel.vercel.app`) and let it redeploy. (Optional — `*` works
   for a public demo, but this is tidy.)
2. Open the Vercel URL. The Overview page should fill in within a few seconds
   (longer on the very first hit if Render was asleep).

---

## 4. Verify

- `GET https://<api>/health` → `{"status":"ok","database":true,"risk_model":true,...}`
- `GET https://<api>/stats/summary` → non-zero counts (the seed ran)
- Dashboard Overview shows tiles + the decisions breakdown
- Live Stream lists rows; clicking one opens Investigation

---

## 5. Demo tips

- **Warm the API** a minute before recording (open `/health`).
- **Add live traffic** during the demo — point the simulator at production:
  ```bash
  cd backend
  python simulator/simulate_payments.py --api https://<your-api>.onrender.com
  ```
  New rows animate into the Live Stream as they land.
- **Real LLM explanations:** set `PAYSENTINEL_USE_LLM=1` and `ANTHROPIC_API_KEY`
  in Render, redeploy. New decisions then get Claude-written explanations; the
  Investigation page shows an `llm` badge instead of `template`. Existing seeded
  rows keep their template text — re-seed (clear the DB / redeploy) or send fresh
  events to get LLM ones.
