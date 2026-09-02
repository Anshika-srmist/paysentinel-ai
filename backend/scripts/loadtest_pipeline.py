"""
Throughput / latency check for the risk pipeline.

Drives events straight through feature-extraction -> score -> decide ->
recovery -> explain -> persist (no HTTP layer), against a throwaway
in-memory SQLite DB, and reports per-event latency percentiles. Use it to
sanity-check that the pipeline keeps up with the simulator and to catch
regressions in per-event cost.

    cd backend
    python scripts/loadtest_pipeline.py --count 1000
    PAYSENTINEL_USE_LLM=1 python scripts/loadtest_pipeline.py --count 50   # measure the LLM path
"""
import argparse
import os
import random
import statistics
import sys
import time
import uuid
from datetime import datetime, timedelta

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db.database import Base
from app.engine.pipeline import process_event
from app.models.orm_models import PaymentEvent

_METHODS = ["UPI", "CARD", "NETBANKING", "WALLET"]
_FAIL_REASONS = [None, "BANK_TIMEOUT", "CARD_DECLINED", "INSUFFICIENT_FUNDS",
                 "SUSPECTED_FRAUD", "MULTIPLE_FAILED_ATTEMPTS"]


def _random_event(i: int) -> PaymentEvent:
    failed = random.random() < 0.35
    reason = random.choice(_FAIL_REASONS[1:]) if failed else None
    return PaymentEvent(
        transaction_id=f"TXN_{uuid.uuid4().hex[:10].upper()}",
        customer_id=f"CUST_{random.randint(1, 40)}",
        merchant_id=f"MER_{random.randint(1, 15)}",
        amount=round(random.uniform(200, 60000), 2),
        payment_method=random.choice(_METHODS),
        bank="HDFC",
        device_id=f"DEVICE_{random.randint(1, 50)}",
        status="FAILED" if failed else "SUCCESS",
        failure_reason=reason,
        event_time=datetime(2026, 9, 1) + timedelta(seconds=i * 3),
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Risk pipeline load test")
    parser.add_argument("--count", type=int, default=500)
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args()
    random.seed(args.seed)

    engine = create_engine("sqlite://", connect_args={"check_same_thread": False},
                           poolclass=StaticPool)
    Base.metadata.create_all(bind=engine)
    db = sessionmaker(bind=engine)()

    llm = os.getenv("PAYSENTINEL_USE_LLM", "0") == "1"
    print(f"Running {args.count} events through the pipeline (LLM path: {'on' if llm else 'off'})...")

    latencies_ms = []
    wall_start = time.perf_counter()
    for i in range(args.count):
        event = _random_event(i)
        db.add(event)
        db.commit()
        db.refresh(event)

        t0 = time.perf_counter()
        process_event(db, event)
        latencies_ms.append((time.perf_counter() - t0) * 1000)
    wall = time.perf_counter() - wall_start

    latencies_ms.sort()
    def pct(p: float) -> float:
        return latencies_ms[min(len(latencies_ms) - 1, int(p / 100 * len(latencies_ms)))]

    print(f"\n  events         : {args.count}")
    print(f"  wall clock     : {wall:.2f}s")
    print(f"  throughput     : {args.count / wall:.1f} events/s")
    print(f"  latency mean   : {statistics.mean(latencies_ms):.1f} ms")
    print(f"  latency p50    : {pct(50):.1f} ms")
    print(f"  latency p95    : {pct(95):.1f} ms")
    print(f"  latency p99    : {pct(99):.1f} ms")
    print(f"  latency max    : {latencies_ms[-1]:.1f} ms")
    db.close()


if __name__ == "__main__":
    main()
