"""Alembic migration environment.

The database URL is taken from the application (``app.db.database.DATABASE_URL``),
which is itself driven by the ``DATABASE_URL`` env var — so migrations always
target the same database the app does, with no URL duplicated in alembic.ini.
"""
import os
import sys
from logging.config import fileConfig

from sqlalchemy import engine_from_config, pool

from alembic import context

# Make the `app` package importable when Alembic runs from the backend/ dir.
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from app.db.database import DATABASE_URL  # noqa: E402
from app.models import orm_models  # noqa: E402,F401  (registers tables on Base.metadata)
from app.db.database import Base  # noqa: E402

config = context.config
config.set_main_option("sqlalchemy.url", DATABASE_URL)

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    context.configure(
        url=DATABASE_URL,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            compare_type=True,
            render_as_batch=connection.dialect.name == "sqlite",
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
