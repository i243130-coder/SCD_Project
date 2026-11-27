"""Alembic env: sync driver URL derived from the app settings (asyncpg -> psycopg / aiosqlite -> sqlite)."""

from __future__ import annotations

import os
import sys
from pathlib import Path

from alembic import context
from sqlalchemy import create_engine

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from ivcommon.config import get_settings  # noqa: E402
from src.models.tables import Base  # noqa: E402


def sync_url() -> str:
    url = os.environ.get("ALEMBIC_URL") or get_settings().sqlalchemy_url
    return url.replace("+asyncpg", "+psycopg").replace("+aiosqlite", "")


def run() -> None:
    engine = create_engine(sync_url())
    with engine.connect() as conn:
        context.configure(connection=conn, target_metadata=Base.metadata)
        with context.begin_transaction():
            context.run_migrations()


run()
