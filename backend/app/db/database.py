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


def _migrate_prompts() -> None:
    """Add new columns to prompts if they don't exist."""
    new_columns: list[tuple[str, str]] = [
        ("mode", "TEXT NOT NULL DEFAULT 'ai'"),
        ("vary_decoration", "BOOLEAN NOT NULL DEFAULT 1"),
    ]
    with engine.begin() as conn:
        cols = conn.execute(text("PRAGMA table_info(prompts)")).fetchall()
        existing = {row[1] for row in cols}
        for name, ddl in new_columns:
            if name not in existing:
                conn.execute(
                    text(f"ALTER TABLE prompts ADD COLUMN {name} {ddl}")
                )
                log.info("migrated: added column prompts.%s", name)


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
        ("min_interval_minutes", "INTEGER NOT NULL DEFAULT 60"),
        ("max_interval_minutes", "INTEGER NOT NULL DEFAULT 240"),
        ("active_hours_start", "INTEGER NOT NULL DEFAULT 9"),
        ("active_hours_end", "INTEGER NOT NULL DEFAULT 22"),
    ]
    with engine.begin() as conn:
        cols = conn.execute(text("PRAGMA table_info(x_accounts)")).fetchall()
        existing = {row[1] for row in cols}
        for name, ddl in new_columns:
            if name not in existing:
                conn.execute(
                    text(f"ALTER TABLE x_accounts ADD COLUMN {name} {ddl}")
                )
                log.info("migrated: added column x_accounts.%s", name)
