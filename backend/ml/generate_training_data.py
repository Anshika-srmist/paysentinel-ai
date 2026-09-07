"""
Generates a labelled training dataset for the risk model.

Unlike the earlier version (which emitted independent events), this builds
a **timeline per customer** over a simulated window, then computes the
model features from each event's position in that timeline — so velocity,
recency, failure-ratio and device-sharing features carry real signal
rather than being drawn from a distribution.

Fraud is injected as **archetypes** on top of otherwise-normal timelines:

  card_testing      a burst of many tiny transactions in minutes, often a
                    fresh device, some failures
  account_takeover  after a long clean history: new device + new method +
                    a big amount, often at an odd hour
  bust_out          a ramp — normal for weeks, then escalating amount and
                    frequency
  ring              several fresh accounts sharing one device, similar
                    amounts, a tight time window

Hard negatives are kept deliberately: legit big-ticket buys, a genuine new
device, a method switch, a short retry run after a flaky bank. Plus ~2.5%
symmetric label noise, because real chargeback/review labels are noisy and
a spotless split produces a useless 100%.
"""
import math
import os
import random
from collections import defaultdict
from datetime import datetime, timedelta

import pandas as pd

from app.engine.features_common import FEATURE_NAMES, assemble

SEED = 42
WINDOW_DAYS = 45
N_REGULAR = 380
METHODS = ["UPI", "CARD", "NETBANKING", "WALLET"]
# Large pool so a legit customer's device is almost never shared — that's
# what lets the ring / card-testing shared devices stand out as signal.
DEVICE_POOL = [f"DEV_{i}" for i in range(1, 2600)]
LABEL_NOISE_RATE = 0.02

FRAUD_FRACTIONS = {          # of regular customers who suffer each archetype
    "card_testing": 0.16,
    "account_takeover": 0.11,
    "bust_out": 0.07,
}
N_RINGS = 30


def _profile(rng: random.Random) -> dict:
    low = rng.choice([150, 300, 500, 800])
    return {
        "typical_low": low,
        "typical_high": low * rng.choice([3, 4, 6, 9]),
        "usual_method": rng.choice(METHODS),
        "usual_device": rng.choice(DEVICE_POOL),
        "day_rate": rng.uniform(0.1, 1.4),       # events/day
        "center_hour": rng.choice([9, 10, 12, 13, 18, 19, 20, 21]),
    }


def _legit_amount(rng: random.Random, p: dict) -> float:
    return round(rng.uniform(p["typical_low"], p["typical_high"]) * rng.lognormvariate(0, 0.25), 2)


def _legit_hour(rng: random.Random, p: dict) -> int:
    return int(min(23, max(0, round(rng.gauss(p["center_hour"], 2.5))))) % 24


def _build_regular_timeline(rng: random.Random, cid: str, p: dict, start: datetime) -> list[dict]:
    events, t = [], start + timedelta(hours=rng.uniform(0, 48))
    end = start + timedelta(days=WINDOW_DAYS)
    while t < end:
        method, device = p["usual_method"], p["usual_device"]
        amount = _legit_amount(rng, p)
        hour = _legit_hour(rng, p)
        status = "SUCCESS"
        r = rng.random()
        if r < 0.10:                                   # legit big-ticket
            amount = round(p["typical_high"] * rng.uniform(2, 6), 2)
        if rng.random() < 0.05:                        # genuine new device
            device = rng.choice(DEVICE_POOL)
        if rng.random() < 0.03:                        # legit method switch
            method = rng.choice(METHODS)
        if rng.random() < 0.06:                        # a flaky-bank failure
            status = "FAILED"
        events.append(dict(customer_id=cid, ts=t, amount=amount, device_id=device,
                           payment_method=method, hour=t.hour if False else hour,
                           status=status, is_risky=0))
        gap_hours = rng.expovariate(1.0) * 24.0 / max(0.05, p["day_rate"])
        t += timedelta(hours=max(0.05, gap_hours))
    return events


def _inject_card_testing(rng: random.Random, tl: list[dict], p: dict) -> None:
    if len(tl) < 5:
        return
    i = rng.randint(2, len(tl) - 2)
    base = tl[i]["ts"]
    device = rng.choice(DEVICE_POOL) if rng.random() < 0.8 else p["usual_device"]
    burst = []
    for k in range(rng.randint(10, 30)):                # a real burst — velocity is the tell
        burst.append(dict(
            customer_id=tl[0]["customer_id"], ts=base + timedelta(seconds=k * rng.uniform(3, 25)),
            amount=round(rng.uniform(1, 60), 2), device_id=device,
            payment_method=rng.choice(METHODS), hour=(base.hour),
            status="FAILED" if rng.random() < 0.35 else "SUCCESS", is_risky=1,
        ))
    tl.extend(burst)


def _inject_account_takeover(rng: random.Random, tl: list[dict], p: dict) -> None:
    if len(tl) < 12:
        return
    i = rng.randint(len(tl) - 6, len(tl) - 1)
    base = tl[i]["ts"] + timedelta(hours=rng.uniform(1, 20))
    device = rng.choice(DEVICE_POOL)                    # always a fresh device
    method = rng.choice([m for m in METHODS if m != p["usual_method"]])
    for k in range(rng.randint(2, 5)):
        tl.append(dict(
            customer_id=tl[0]["customer_id"], ts=base + timedelta(minutes=k * rng.uniform(3, 40)),
            amount=round(p["typical_high"] * rng.uniform(5, 20), 2),
            device_id=device, payment_method=method,
            hour=rng.choice([1, 2, 3, 4, 5, 23]) if rng.random() < 0.7 else rng.randint(9, 20),
            status="SUCCESS" if rng.random() < 0.7 else "FAILED", is_risky=1,
        ))


def _inject_bust_out(rng: random.Random, tl: list[dict], p: dict) -> None:
    if len(tl) < 10:
        return
    amt = p["typical_high"] * rng.uniform(1.1, 1.6)
    t = tl[-1]["ts"]
    for step in range(rng.randint(6, 11)):
        amt *= rng.uniform(1.3, 1.8)
        t += timedelta(hours=rng.uniform(0.4, 4))
        tl.append(dict(
            customer_id=tl[0]["customer_id"], ts=t, amount=round(amt, 2),
            device_id=p["usual_device"] if rng.random() < 0.5 else rng.choice(DEVICE_POOL),
            payment_method=p["usual_method"], hour=t.hour,
            status="SUCCESS",
            # the first two ramp steps are genuinely indistinguishable from a
            # legit spending increase — don't label them fraud, only the tail
            is_risky=0 if step < 2 else 1,
        ))


def _ring_events(rng: random.Random, ring_idx: int, start: datetime) -> list[dict]:
    device = f"DEV_RING_{ring_idx}"
    members = [f"CUST_RING_{ring_idx}_{j}" for j in range(rng.randint(3, 5))]
    base_amount = rng.choice([4000, 6500, 9000, 14000])
    t0 = start + timedelta(days=rng.uniform(3, WINDOW_DAYS - 3), hours=rng.uniform(0, 22))
    out = []
    for k in range(rng.randint(10, 22)):
        out.append(dict(
            customer_id=members[k % len(members)],
            ts=t0 + timedelta(minutes=k * rng.uniform(2, 9)),
            amount=round(base_amount * rng.uniform(0.95, 1.06), 2),
            device_id=device, payment_method="CARD",
            hour=(t0.hour), status="SUCCESS" if k % 5 else "FAILED", is_risky=1,
        ))
    # a few clean-looking priors for each member so history isn't empty
    for m in members:
        for j in range(rng.randint(1, 3)):
            out.append(dict(
                customer_id=m, ts=t0 - timedelta(days=rng.uniform(1, 20)),
                amount=round(rng.uniform(300, 2500), 2), device_id=rng.choice(DEVICE_POOL),
                payment_method=rng.choice(METHODS), hour=rng.randint(8, 21),
                status="SUCCESS", is_risky=0,
            ))
    return out


def _feature_rows(all_events: list[dict]) -> list[dict]:
    """Compute the model features for every event from its customer timeline."""
    by_cust: dict[str, list[dict]] = defaultdict(list)
    for e in all_events:
        by_cust[e["customer_id"]].append(e)

    # device -> set of customers, for device_shared_count
    dev_customers: dict[str, set] = defaultdict(set)
    for e in all_events:
        dev_customers[e["device_id"]].add(e["customer_id"])

    rows = []
    for cid, evs in by_cust.items():
        evs.sort(key=lambda x: x["ts"])
        seen_devices: set = set()
        seen_methods: set = set()
        for idx, e in enumerate(evs):
            prior = evs[:idx]
            prior_ok_amounts = [p["amount"] for p in prior if p["status"] == "SUCCESS"] or [p["amount"] for p in prior]
            mean = sum(prior_ok_amounts) / len(prior_ok_amounts) if prior_ok_amounts else None
            std = (
                math.sqrt(sum((a - mean) ** 2 for a in prior_ok_amounts) / len(prior_ok_amounts))
                if prior_ok_amounts and len(prior_ok_amounts) > 1 else None
            )
            typical = mean
            recent = prior[-10:]
            fail_ratio = (sum(1 for p in recent if p["status"] == "FAILED") / len(recent)) if recent else 0.0
            streak = 0
            for p in reversed(prior):
                if p["status"] == "FAILED":
                    streak += 1
                else:
                    break
            v1h = sum(1 for p in prior if (e["ts"] - p["ts"]).total_seconds() <= 3600)
            v24h = sum(1 for p in prior if (e["ts"] - p["ts"]).total_seconds() <= 86400)
            secs_since = (e["ts"] - prior[-1]["ts"]).total_seconds() if prior else None
            dsc = len(dev_customers[e["device_id"]] - {cid})

            feats = assemble(
                amount=e["amount"], typical_amount=typical, amount_mean=mean, amount_std=std,
                is_new_device=bool(prior) and e["device_id"] not in seen_devices,
                is_new_payment_method=bool(prior) and e["payment_method"] not in seen_methods,
                event_hour=e["hour"], recent_failed_count=streak, customer_fail_ratio=fail_ratio,
                velocity_1h=v1h, velocity_24h=v24h, secs_since_last=secs_since, device_shared_count=dsc,
            )
            feats["is_risky"] = e["is_risky"]
            rows.append(feats)
            seen_devices.add(e["device_id"])
            seen_methods.add(e["payment_method"])
    return rows


def generate_dataset(seed: int = SEED) -> pd.DataFrame:
    rng = random.Random(seed)
    start = datetime(2026, 1, 1)
    all_events: list[dict] = []

    ids = [f"CUST_{i}" for i in range(1, N_REGULAR + 1)]
    profiles = {cid: _profile(rng) for cid in ids}
    timelines = {cid: _build_regular_timeline(rng, cid, profiles[cid], start) for cid in ids}

    def _sample(frac):
        return set(rng.sample(ids, int(N_REGULAR * frac)))

    for cid in _sample(FRAUD_FRACTIONS["card_testing"]):
        _inject_card_testing(rng, timelines[cid], profiles[cid])
    for cid in _sample(FRAUD_FRACTIONS["account_takeover"]):
        _inject_account_takeover(rng, timelines[cid], profiles[cid])
    for cid in _sample(FRAUD_FRACTIONS["bust_out"]):
        _inject_bust_out(rng, timelines[cid], profiles[cid])

    for tl in timelines.values():
        all_events.extend(tl)
    for r in range(N_RINGS):
        all_events.extend(_ring_events(rng, r, start))

    rows = _feature_rows(all_events)
    for row in rows:                                   # symmetric label noise, applied last
        if rng.random() < LABEL_NOISE_RATE:
            row["is_risky"] = 1 - row["is_risky"]

    df = pd.DataFrame(rows)[[*FEATURE_NAMES, "is_risky"]]
    return df.sample(frac=1, random_state=seed).reset_index(drop=True)


if __name__ == "__main__":
    df = generate_dataset()
    out_path = os.path.join(os.path.dirname(__file__), "training_data.csv")
    df.to_csv(out_path, index=False)
    print(f"Generated {len(df)} rows -> {out_path}")
    print(f"Risky rate: {df['is_risky'].mean():.4f}  ({int(df['is_risky'].sum())} risky / {len(df)} total)")
    print(df.describe().T[["mean", "std", "min", "max"]].round(3))
