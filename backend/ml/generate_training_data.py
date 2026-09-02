"""
Generates a labeled training dataset for the risk model.

We reuse the simulator's scenario logic (same customer profiles, same
amount/device patterns) but additionally compute the interpretable
features the model will actually train on, and attach a ground-truth
label (is_risky) based on which scenario generated the event.

Why not just use the simulator's raw output directly? Because the model
needs *engineered* features (ratios, flags) rather than raw fields —
this file is the bridge between "realistic event" and "trainable row".
"""
import random
import sys
import os
from datetime import datetime, timedelta

import pandas as pd

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "simulator"))
from simulate_payments import CUSTOMERS, MERCHANTS, BANKS, METHODS, DEVICES, SCENARIOS, SCENARIO_WEIGHTS  # noqa: E402


# Fraction of rows whose ground-truth label is deliberately flipped. Real
# fraud labels come from chargebacks and manual review weeks later and are
# themselves noisy; a couple of percent of symmetric label noise also stops
# a high-capacity model (Random Forest) from finding a perfect split and
# reporting a useless 100% — see the note in generate_dataset().
LABEL_NOISE_RATE = 0.02


def engineer_features(scenario: str, customer_id: str, amount: float, device_id: str,
                       payment_method: str, event_hour: int, recent_failed_count: int) -> dict:
    profile = CUSTOMERS[customer_id]
    typical_mid = (profile["typical_low"] + profile["typical_high"]) / 2

    return {
        "amount": amount,
        "amount_ratio_to_typical": round(amount / typical_mid, 3),
        "is_new_device": int(device_id != profile["usual_device"]),
        "is_new_payment_method": int(payment_method != profile["usual_method"]),
        "is_unusual_hour": int(not (6 <= event_hour <= 23)),
        "recent_failed_count": recent_failed_count,
        # ground truth — this is what we're training to predict
        "is_risky": int(scenario in ("fraud", "suspicious")),
        "scenario": scenario,  # kept for analysis, dropped before training
    }


def generate_dataset(n_rows: int = 8000, seed: int = 42) -> pd.DataFrame:
    random.seed(seed)
    rows = []
    for _ in range(n_rows):
        scenario = random.choices(SCENARIOS, weights=SCENARIO_WEIGHTS, k=1)[0]
        customer_id = random.choice(list(CUSTOMERS.keys()))
        profile = CUSTOMERS[customer_id]

        event_hour = random.randint(0, 23)
        recent_failed_count = 0

        # Noise knobs below are deliberate: real payment behaviour overlaps
        # heavily between classes (people make big legit purchases from new
        # phones; card-testing fraud starts with *small* amounts on a stolen
        # but familiar session). Without this overlap the task is trivially
        # separable and a Random Forest reports a suspicious, useless 100%.
        # The goal is genuine distribution overlap on every feature, not just
        # on `amount`.

        if scenario == "success":
            amount = random.uniform(profile["typical_low"], profile["typical_high"])
            device_id = profile["usual_device"]
            payment_method = profile["usual_method"]
            # ~15%: a legitimate big-ticket purchase (new phone, rent, a gift)
            # — same customer, same device, just a much bigger amount
            if random.random() < 0.15:
                amount = profile["typical_high"] * random.uniform(2, 7)
            # ~12%: customer genuinely on a new device (new phone, work laptop)
            if random.random() < 0.12:
                device_id = random.choice(DEVICES)
            # ~6%: added a new card / switched method legitimately
            if random.random() < 0.06:
                payment_method = random.choice(METHODS)
            # ~10%: a couple of recent failures before this success (bank was
            # flaky, they retried) — so a short failure run isn't risk-only
            if random.random() < 0.10:
                recent_failed_count = random.randint(1, 3)

        elif scenario == "temporary_failure":
            amount = random.uniform(profile["typical_low"], profile["typical_high"])
            device_id = profile["usual_device"]
            payment_method = profile["usual_method"]
            recent_failed_count = random.randint(0, 3)

        elif scenario == "fraud":
            # Amount ranges from *slightly* above normal (card testing) to a
            # wild outlier — a low floor is what creates the overlap.
            amount = profile["typical_high"] * random.uniform(1.2, 40)
            device_id = random.choice(DEVICES)
            # ~45%: a card/method the customer has never used (fraudster's own
            # instrument); the rest ride the saved method
            payment_method = random.choice(METHODS) if random.random() < 0.45 else profile["usual_method"]
            event_hour = random.choice(list(range(0, 6)) + list(range(0, 24)))
            recent_failed_count = random.randint(0, 2)
            # ~35%: fraud on the usual device (stolen session / saved card /
            # account takeover) — device must not be a near-perfect tell
            if random.random() < 0.35:
                device_id = profile["usual_device"]
            # ~25%: "clean-looking" fraud — normal hour, no prior failures
            if random.random() < 0.25:
                event_hour = random.randint(9, 20)
                recent_failed_count = 0

        elif scenario == "repeated_failure":
            amount = random.uniform(profile["typical_low"], profile["typical_high"])
            device_id = profile["usual_device"]
            payment_method = profile["usual_method"]
            recent_failed_count = random.randint(1, 5)

        else:  # suspicious
            # Some suspicious activity sits near normal amounts and leans on
            # the failed-attempt pattern instead of a big number.
            amount = profile["typical_high"] * random.uniform(0.9, 7)
            device_id = random.choice(DEVICES)
            payment_method = random.choice(METHODS) if random.random() < 0.30 else profile["usual_method"]
            recent_failed_count = random.randint(1, 6)
            # ~40%: from the customer's usual device
            if random.random() < 0.40:
                device_id = profile["usual_device"]

        row = engineer_features(
            scenario, customer_id, amount, device_id, payment_method,
            event_hour, recent_failed_count
        )
        # Symmetric label noise — flip a small fraction of ground-truth
        # labels (see LABEL_NOISE_RATE). Applied last so it's independent of
        # the feature values.
        if random.random() < LABEL_NOISE_RATE:
            row["is_risky"] = 1 - row["is_risky"]
        rows.append(row)

    return pd.DataFrame(rows)


if __name__ == "__main__":
    df = generate_dataset()
    out_path = os.path.join(os.path.dirname(__file__), "training_data.csv")
    df.to_csv(out_path, index=False)
    print(f"Generated {len(df)} rows -> {out_path}")
    print(f"Risky rate: {df['is_risky'].mean():.4f}  ({df['is_risky'].sum()} risky / {len(df)} total)")
    print(df['scenario'].value_counts())
