# Real-mode testing with Razorpay

Drive **actual Razorpay payments** through PaySentinel. This uses Razorpay
**test mode** — the real Razorpay API, real checkout UI, real webhooks — but
test card numbers, so no money moves. (Live payments would need a KYC-verified
Razorpay account and real cards; the code path is identical, so test mode is
what you want for a demo.)

The loop:

```
checkout.html  ──pay──▶  Razorpay (test)  ──webhook──▶  /webhooks/razorpay  ──▶  scored, shown in the dashboard
```

---

## 1. Razorpay account + test keys (5 min, no KYC)

1. Sign up at <https://dashboard.razorpay.com/signup>.
2. Make sure the dashboard is in **Test Mode** (toggle, top-left).
3. **Settings → API Keys → Generate Test Key**. Copy:
   - **Key Id** — `rzp_test_xxxxxxxxxxxxxx`
   - **Key Secret** — shown once

Set them on the backend:

| Env var | Value |
|---|---|
| `RAZORPAY_KEY_ID` | `rzp_test_...` |
| `RAZORPAY_KEY_SECRET` | the secret |

(Render: service → Environment. Local: export them before `uvicorn`.)

---

## 2. Make the backend reachable by Razorpay

Razorpay must POST webhooks to a public HTTPS URL.

- **Deployed backend (Render):** already public — use `https://<your-api>.onrender.com`.
- **Local backend:** tunnel it.
  ```bash
  # one option — cloudflared (no signup)
  cloudflared tunnel --url http://localhost:8000
  # or: ngrok http 8000
  ```
  Use the `https://…` URL it prints.

Call this `<API>` below.

---

## 3. Add the webhook in Razorpay

**Settings → Webhooks → Add New Webhook**

| Field | Value |
|---|---|
| Webhook URL | `<API>/webhooks/razorpay` |
| Secret | any string, e.g. `whsec_paysentinel` |
| Active events | `payment.captured`, `payment.failed` |

Then set the same secret on the backend:

| Env var | Value |
|---|---|
| `PAYSENTINEL_RAZORPAY_WEBHOOK_SECRET` | the secret you just entered |

Restart / redeploy the backend so it picks up all three env vars. Check:

```bash
curl <API>/razorpay/config      # -> {"enabled": true, "key_id": "rzp_test_..."}
```

---

## 4. Pay

Open the checkout page, pointing it at the backend:

- Local: <http://localhost:5173/checkout.html>  (Vite proxies `/api` to `:8000`)
- Deployed frontend: `https://paysentinel-ai.vercel.app/checkout.html?api=<API>&dash=/`

Enter an amount (try a large one + "new device" to trigger a HOLD), click **Pay
with Razorpay**, and in the Razorpay modal use:

| Instrument | Value |
|---|---|
| Card | `4111 1111 1111 1111`, any future expiry, any CVV, any OTP |
| UPI | `success@razorpay` (or `failure@razorpay` to test a decline) |

More test instruments: <https://razorpay.com/docs/payments/payments/test-card-details/>

---

## 5. Watch it score

Within a second or two of the payment, Razorpay fires the webhook and
PaySentinel scores it. Check:

```bash
curl <API>/decisions?limit=3
```

or open the dashboard → **Live stream** — the payment appears as a real event
(`pay_...` transaction id) with its decision, and **Investigation** shows the
risk score, signals and explanation.

Webhook not arriving? Razorpay **Settings → Webhooks → your webhook → Recent
Deliveries** shows every attempt and the response body.
