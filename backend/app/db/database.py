from __future__ import annotations

import logging
from collections.abc import Iterator

from sqlalchemy import create_engine, event, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import settings

log = logging.getLogger(__name__)

DB_PATH = settings.data_dir / "xautopost.db"

engine = create_engine(
    f"sqlite:///{DB_PATH}",
    echo=False,
    future=True,
    connect_args={"check_same_thread": False},
)


@event.listens_for(Engine, "connect")
def _sqlite_fk_pragma(dbapi_conn, _):  # type: ignore[no-untyped-def]
    cursor = dbapi_conn.cursor()
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.close()

SessionLocal = sessionmaker(
    bind=engine,
    autocommit=False,
    autoflush=False,
    expire_on_commit=False,
    future=True,
)


def get_db() -> Iterator[Session]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db() -> None:
    from app.db import models  # noqa: F401  ensure tables registered
    from app.db.base import Base

    Base.metadata.create_all(bind=engine)
    _migrate_x_accounts()
    _migrate_operators()
    _migrate_prompts()


def _drop_legacy_column(conn, table: str, column: str) -> None:  # type: ignore[no-untyped-def]
    """Drop a column the model no longer maps. Required because SQLAlchemy's
    `mapped_column(default=...)` is a Python-side default — `create_all()`
    emits the column as `NOT NULL` *without* a SQL DEFAULT, so once the model
    stops listing the column, every new INSERT fails the NOT NULL check on
    the still-present table column. SQLite ≥3.35 supports DROP COLUMN
    directly; older versions fail and the migration logs the error and moves
    on (the user will hit the IntegrityError again, but the rest of the
    schema stays consistent)."""
    cols = conn.execute(text(f"PRAGMA table_info({table})")).fetchall()
    if column not in {row[1] for row in cols}:
        return
    try:
        conn.execute(text(f"ALTER TABLE {table} DROP COLUMN {column}"))
        log.info("migrated: dropped legacy column %s.%s", table, column)
    except Exception:  # noqa: BLE001
        log.exception("failed to drop legacy column %s.%s", table, column)


def _migrate_prompts() -> None:
    """Add new columns to prompts if they don't exist."""
    new_columns: list[tuple[str, str]] = [
        ("mode", "TEXT NOT NULL DEFAULT 'ai'"),
        ("decorate_emoji", "BOOLEAN NOT NULL DEFAULT 1"),
        ("decorate_letters", "BOOLEAN NOT NULL DEFAULT 0"),
    ]
    with engine.begin() as conn:
        cols = conn.execute(text("PRAGMA table_info(prompts)")).fetchall()
        existing = {row[1] for row in cols}
        added: set[str] = set()
        for name, ddl in new_columns:
            if name not in existing:
                conn.execute(
                    text(f"ALTER TABLE prompts ADD COLUMN {name} {ddl}")
                )
                log.info("migrated: added column prompts.%s", name)
                added.add(name)
        # Backfill: when splitting the boolean `vary_decoration` into two flags,
        # carry over the old value so users who had it off stay off.
        if "decorate_emoji" in added and "vary_decoration" in existing:
            conn.execute(
                text("UPDATE prompts SET decorate_emoji = vary_decoration")
            )
            log.info("migrated: backfilled prompts.decorate_emoji from vary_decoration")
        # Old DBs created via SQLAlchemy `create_all` while the model still
        # listed `vary_decoration` get a NOT NULL column with no SQL default;
        # after the model dropped the field, INSERTs would fail. Drop it.
        _drop_legacy_column(conn, "prompts", "vary_decoration")


def _migrate_operators() -> None:
    """Add new columns to operators if they don't exist."""
    new_columns: list[tuple[str, str]] = [
        ("rotation_interval_seconds", "INTEGER NOT NULL DEFAULT 5"),
    ]
    with engine.begin() as conn:
        cols = conn.execute(text("PRAGMA table_info(operators)")).fetchall()
        existing = {row[1] for row in cols}
        for name, ddl in new_columns:
            if name not in existing:
                conn.execute(
                    text(f"ALTER TABLE operators ADD COLUMN {name} {ddl}")
                )
                log.info("migrated: added column operators.%s", name)


def _migrate_x_accounts() -> None:
    """Add new columns to x_accounts if they don't exist (lightweight ALTER)."""
    new_columns: list[tuple[str, str]] = [
        (
            "default_prompt_id",
            "INTEGER REFERENCES prompts(id) ON DELETE SET NULL",
        ),
        ("posting_enabled", "BOOLEAN NOT NULL DEFAULT 0"),
        ("min_interval_seconds", "INTEGER NOT NULL DEFAULT 3600"),
        ("max_interval_seconds", "INTEGER NOT NULL DEFAULT 14400"),
        ("active_hours_start", "INTEGER NOT NULL DEFAULT 9"),
        ("active_hours_end", "INTEGER NOT NULL DEFAULT 22"),
    ]
    with engine.begin() as conn:
        cols = conn.execute(text("PRAGMA table_info(x_accounts)")).fetchall()
        existing = {row[1] for row in cols}
        added: set[str] = set()
        for name, ddl in new_columns:
            if name not in existing:
                conn.execute(
                    text(f"ALTER TABLE x_accounts ADD COLUMN {name} {ddl}")
                )
                log.info("migrated: added column x_accounts.%s", name)
                added.add(name)
        # Backfill: when promoting the interval from minutes to seconds,
        # multiply the old value so existing accounts keep their cadence.
        if "min_interval_seconds" in added and "min_interval_minutes" in existing:
            conn.execute(
                text(
                    "UPDATE x_accounts "
                    "SET min_interval_seconds = min_interval_minutes * 60"
                )
            )
            log.info("migrated: backfilled x_accounts.min_interval_seconds from minutes")
        if "max_interval_seconds" in added and "max_interval_minutes" in existing:
            conn.execute(
                text(
                    "UPDATE x_accounts "
                    "SET max_interval_seconds = max_interval_minutes * 60"
                )
            )
            log.info("migrated: backfilled x_accounts.max_interval_seconds from minutes")
        # Old DBs created via SQLAlchemy `create_all` while the model still
        # listed the *_minutes fields get NOT NULL columns without SQL
        # DEFAULTs; after the model switched to seconds, the next account
        # INSERT failed because SQLAlchemy no longer emits those columns
        # and SQLite has no value to fall back to. Drop them.
        _drop_legacy_column(conn, "x_accounts", "min_interval_minutes")
        _drop_legacy_column(conn, "x_accounts", "max_interval_minutes")
