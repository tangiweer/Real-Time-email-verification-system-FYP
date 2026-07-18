"""
Async SQLite setup via SQLAlchemy + aiosqlite.
SQLite is good enough for an FYP — swap to Postgres if this ever sees real traffic.
"""

from __future__ import annotations

import os
import logging
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from sqlalchemy.orm import declarative_base

logger = logging.getLogger("email_verifier.database")

# Make sure the data dir exists before SQLite tries to write there
_PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
_DATA_DIR = os.path.join(_PROJECT_ROOT, "data")
os.makedirs(_DATA_DIR, exist_ok=True)

# Bulk uploads land here
UPLOAD_DIR = os.path.join(_DATA_DIR, "uploads")
os.makedirs(UPLOAD_DIR, exist_ok=True)

DB_PATH = os.path.join(_DATA_DIR, "email_verifier.db")
DATABASE_URL = f"sqlite+aiosqlite:///{DB_PATH}"

# Async engine — the check_same_thread flag is required because
# aiosqlite dispatches queries from different threads under the hood
engine = create_async_engine(
    DATABASE_URL,
    echo=False,
    # aiosqlite uses background threads, so SQLite's default same-thread check would blow up
    connect_args={"check_same_thread": False}
)

# Session factory — one session per request, no autocommit/autoflush so we control transaction boundaries
AsyncSessionLocal = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autocommit=False,
    autoflush=False,
)

Base = declarative_base()

async def init_db() -> None:
    """Bootstrap tables on first run. Safe to call repeatedly."""
    try:
        from app.db_models import User, BulkJob, VerificationLog
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        logger.info(f"[database] Initialized SQLite database at {DB_PATH}")
    except Exception as e:
        logger.error(f"[database] Failed to initialize DB: {e}")

async def get_db_session():
    """FastAPI dependency — yields a session and cleans up when the request is done."""
    async with AsyncSessionLocal() as session:
        try:
            yield session
        finally:
            await session.close()
