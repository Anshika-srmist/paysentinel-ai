"""
Backfill: run the risk pipeline for any payment_events that don't yet have
a risk_decisions row.

Useful after ingesting events while the pipeline was disabled/broken, or
after changing the engine and wanting to re-score history (pass --rescore
to delete existing decisions first).

    cd backend
    python scripts/backfill_decisions.py
    python scripts/backfill_decisions.py --rescore --limit 500
"""
import argparse
import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.db.database import SessionLocal
from app.engine.pipeline import process_event
from app.models.orm_models import PaymentEvent, RiskDecision


def main() -> None:
    parser = argparse.ArgumentParser(description="Backfill risk decisions for existing events")
    parser.add_argument("--rescore", action="store_true",
                        help="delete all existing decisions and re-score every event")
    parser.add_argument("--limit", type=int, default=0, help="cap the number of events processed (0 = all)")
    args = parser.parse_args()

    # Schema is managed by Alembic — run `alembic upgrade head` first if the
    # database is new.
    db = SessionLocal()
    try:
        if args.rescore:
            deleted = db.query(RiskDecision).delete()
            db.commit()
            print(f"--rescore: deleted {deleted} existing decisions")

        scored_event_ids = {row[0] for row in db.query(RiskDecision.event_id).all()}
        query = db.query(PaymentEvent).order_by(PaymentEvent.id.asc())
        pending = [e for e in query.all() if e.id not in scored_event_ids]
        if args.limit:
            pending = pending[: args.limit]

        if not pending:
            print("Nothing to backfill - every event already has a decision.")
            return

        print(f"Backfilling {len(pending)} event(s)...")
        start = time.perf_counter()
        ok = 0
        for event in pending:
            try:
                process_event(db, event)
                ok += 1
            except Exception as exc:  # noqa: BLE001
                print(f"  [skip] event {event.id} ({event.transaction_id}): {exc}")
        elapsed = time.perf_counter() - start
        print(f"Done - {ok}/{len(pending)} scored in {elapsed:.1f}s "
              f"({ok / elapsed:.1f} events/s)" if elapsed else f"Done - {ok} scored")
    finally:
        db.close()


if __name__ == "__main__":
    main()
