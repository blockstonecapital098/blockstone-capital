"""
Database connection and session factory using SQLAlchemy AsyncEngine.
Supports TimescaleDB / PostgreSQL and SQLite aiosqlite for local testing.
"""
from __future__ import annotations
import logging
from contextlib import asynccontextmanager
from typing import AsyncGenerator
from sqlalchemy.ext.asyncio import (
    create_async_engine,
    async_sessionmaker,
    AsyncSession,
    AsyncEngine
)
from sqlalchemy.orm import declarative_base

logger = logging.getLogger(__name__)
Base = declarative_base()

_engine: AsyncEngine | None = None
_session_factory: async_sessionmaker[AsyncSession] | None = None


def init_db(database_url: str = "sqlite+aiosqlite:///./trading.db") -> AsyncEngine:
    """Initializes async database engine and table schemas."""
    global _engine, _session_factory
    _engine = create_async_engine(
        database_url,
        echo=False,
        future=True,
    )
    _session_factory = async_sessionmaker(
        _engine,
        expire_on_commit=False,
        class_=AsyncSession
    )
    logger.info("Database engine initialized for %s", database_url)
    return _engine


@asynccontextmanager
async def get_session() -> AsyncGenerator[AsyncSession, None]:
    """Context manager providing an async transactional session."""
    global _session_factory
    if _session_factory is None:
        init_db()
    
    assert _session_factory is not None
    async with _session_factory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


async def close_db():
    global _engine
    if _engine:
        await _engine.dispose()
        logger.info("Database connection pool disposed.")
