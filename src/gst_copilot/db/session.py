"""Database engine and sessions (SQLAlchemy 2, async, asyncpg driver)."""

from collections.abc import AsyncIterator
from functools import lru_cache

from sqlalchemy import text
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from gst_copilot.config import get_settings


@lru_cache
def get_engine() -> AsyncEngine:
    # pool_pre_ping: check a pooled connection is alive before using it,
    # so a database restart doesn't cause errors on the next requests.
    s = get_settings()
    kw: dict[str, object] = {"pool_pre_ping": True}
    if "sqlite" not in s.database_url:
        kw.update(
            pool_size=s.db_pool_size,
            max_overflow=s.db_max_overflow,
            pool_timeout=s.db_pool_timeout,
        )
    return create_async_engine(s.database_url, **kw)


@lru_cache
def get_sessionmaker() -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(get_engine(), expire_on_commit=False)


async def get_session() -> AsyncIterator[AsyncSession]:
    """FastAPI dependency: one session per request, always closed afterwards."""
    async with get_sessionmaker()() as session:
        yield session


async def ping_database() -> None:
    """Raise if the database can't answer a trivial query."""
    async with get_engine().connect() as conn:
        await conn.execute(text("SELECT 1"))
