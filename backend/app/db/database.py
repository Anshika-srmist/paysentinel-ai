"""
Database setup for PaySentinel AI.

Using SQLite for the buildathon MVP — zero setup, no server to manage under
time pressure. Swapping to PostgreSQL later (for the FinSentinel extension)
is a one-line change: just replace DATABASE_URL below. The schema itself
was designed to migrate cleanly — no SQLite-specific quirks are relied on.
"""
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import sessionmaker, declarative_base

DATABASE_URL = "sqlite:///./paysentinel.db"

engine = create_engine(
    DATABASE_URL, connect_args={"check_same_thread": False}
)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


# Columns added after a table's first release. SQLite can't add these via
# create_all() once the table exists, so we add them by hand on startup.
_ADDED_COLUMNS = {
    "risk_decisions": {
        "explanation_source": "VARCHAR(20)",
        "recommended_action": "VARCHAR(120)",
        "model_name": "VARCHAR(50)",
        "features_json": "TEXT",
        "signals_json": "TEXT",
        "ml_risk": "NUMERIC(5, 4)",
        "behavioral_risk": "NUMERIC(5, 4)",
        "network_risk": "NUMERIC(5, 4)",
        "rule_severity": "VARCHAR(10)",
        "behavioral_json": "TEXT",
        "network_json": "TEXT",
        "audit_json": "TEXT",
        "explanation_json": "TEXT",
    },
}


def run_light_migrations() -> None:
    """
    Dev-only, additive-only schema patch: bring a database created on an
    earlier day up to the current column set without a migration tool.
    Safe to call on every startup; a no-op once the columns exist.
    """
    inspector = inspect(engine)
    tables = set(inspector.get_table_names())
    for table, columns in _ADDED_COLUMNS.items():
        if table not in tables:
            continue  # create_all() will build it complete
        existing = {col["name"] for col in inspector.get_columns(table)}
        missing = {name: ddl for name, ddl in columns.items() if name not in existing}
        if not missing:
            continue
        with engine.begin() as conn:
            for name, ddl in missing.items():
                conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {name} {ddl}"))
