"""
PaySentinel AI — Payment Event Simulator.

We don't have access to Razorpay's live transaction stream, so this
generates realistic-looking payment events across 5 scenario types and
posts them to the ingestion API, so the whole system feels like it's
watching a live feed rather than replaying a CSV.

Usage:
    python simulate_payments.py                # continuous, one event every 2-4s
    python simulate_payments.py --count 200     # fire 200 events quickly, no delay
    python simulate_payments.py --api http://localhost:8000
"""
import argparse
import random
import sys
import time
import uuid
from datetime import datetime, timedelta

import requests

# Windows terminals default to cp1252 and choke on the ₹ / arrow glyphs
# below; force UTF-8 so a demo run doesn't crash mid-stream.
try:
    sys.stdout.reconfigure(encoding="utf-8")
except (AttributeError, ValueError):  # pragma: no cover - non-standard stdout
    pass

BANKS = ["HDFC", "ICICI", "SBI", "Axis", "Kotak", "Yes Bank"]
METHODS = ["UPI", "CARD", "NETBANKING", "WALLET"]
DEVICES = [f"DEVICE_{i}" for i in range(1, 40)]

# A small pool of "regular" customers with a typical spend range each,
# so we can later detect "this is unusual FOR THIS customer" rather
# than just "this is a big number."
CUSTOMERS = {
    f"CUST_{i}": {
        "typical_low": random.choice([200, 500, 800]),
        "typical_high": random.choice([1500, 2000, 3000]),
        "usual_method": random.choice(METHODS),
        "usual_device": random.choice(DEVICES),
    }
    for i in range(1, 61)
}

MERCHANTS = [f"MER_{i}" for i in range(1, 16)]

SCENARIOS = [
    "success",
    "temporary_failure",
    "fraud",
    "repeated_failure",
    "suspicious",
]
# Rough weighting so the feed looks like a realistic payment mix, not
# a 20/20/20/20/20 split of fraud everywhere.
SCENARIO_WEIGHTS = [0.62, 0.15, 0.06, 0.10, 0.07]


def build_event(scenario: str) -> dict:
    customer_id = random.choice(list(CUSTOMERS.keys()))
    profile = CUSTOMERS[customer_id]
    txn_id = f"TXN_{uuid.uuid4().hex[:8].upper()}"
    event_time = datetime.utcnow()

    base = {
        "transaction_id": txn_id,
        "customer_id": customer_id,
        "merchant_id": random.choice(MERCHANTS),
        "payment_method": profile["usual_method"],
        "bank": random.choice(BANKS),
        "device_id": profile["usual_device"],
        "event_time": event_time.isoformat(),
    }

    if scenario == "success":
        base["amount"] = round(random.uniform(profile["typical_low"], profile["typical_high"]), 2)
        base["status"] = "SUCCESS"
        base["failure_reason"] = None

    elif scenario == "temporary_failure":
        base["amount"] = round(random.uniform(profile["typical_low"], profile["typical_high"]), 2)
        base["status"] = "FAILED"
        base["failure_reason"] = random.choice(["BANK_TIMEOUT", "GATEWAY_TIMEOUT", "NETWORK_ERROR"])

    elif scenario == "fraud":
        # amount way above the customer's normal range, new device
        base["amount"] = round(profile["typical_high"] * random.uniform(15, 40), 2)
        base["device_id"] = random.choice(DEVICES)  # not their usual device
        base["status"] = random.choice(["SUCCESS", "FAILED"])
        base["failure_reason"] = None if base["status"] == "SUCCESS" else "SUSPECTED_FRAUD"

    elif scenario == "repeated_failure":
        base["amount"] = round(random.uniform(profile["typical_low"], profile["typical_high"]), 2)
        base["status"] = "FAILED"
        base["failure_reason"] = random.choice(["INSUFFICIENT_FUNDS", "CARD_DECLINED", "UPI_UNAVAILABLE"])

    elif scenario == "suspicious":
        base["amount"] = round(profile["typical_high"] * random.uniform(3, 8), 2)
        base["device_id"] = random.choice(DEVICES)
        base["status"] = "FAILED"
        base["failure_reason"] = "MULTIPLE_FAILED_ATTEMPTS"

    return base


def send_event(api_url: str, event: dict) -> None:
    try:
        resp = requests.post(f"{api_url}/payments", json=event, timeout=5)
        tag = {
            "success": "\033[92mSUCCESS\033[0m",
            "temporary_failure": "\033[93mTEMP-FAIL\033[0m",
            "fraud": "\033[91mFRAUD\033[0m",
            "repeated_failure": "\033[94mREPEAT-FAIL\033[0m",
            "suspicious": "\033[95mSUSPICIOUS\033[0m",
        }
        if resp.status_code == 201:
            print(f"[sent] {event['transaction_id']}  ₹{event['amount']:<10} {event['status']:<8} {event.get('failure_reason') or ''}")
        else:
            print(f"[error {resp.status_code}] {resp.text}")
    except requests.exceptions.RequestException as e:
        print(f"[connection error] {e} — is the API running at {api_url}?")


def main():
    parser = argparse.ArgumentParser(description="PaySentinel payment event simulator")
    parser.add_argument("--api", default="http://localhost:8000", help="Base URL of the FastAPI backend")
    parser.add_argument("--count", type=int, default=0, help="Fire N events quickly and exit (0 = run continuously)")
    parser.add_argument("--min-delay", type=float, default=2.0)
    parser.add_argument("--max-delay", type=float, default=4.0)
    args = parser.parse_args()

    print(f"PaySentinel simulator starting → posting to {args.api}/payments")
    sent = 0
    while True:
        scenario = random.choices(SCENARIOS, weights=SCENARIO_WEIGHTS, k=1)[0]
        event = build_event(scenario)
        send_event(args.api, event)
        sent += 1

        if args.count and sent >= args.count:
            print(f"Done — sent {sent} events.")
            break

        if args.count:
            continue  # burst mode, no delay
        time.sleep(random.uniform(args.min_delay, args.max_delay))


if __name__ == "__main__":
    main()
