"""Async SQLAlchemy database session dependency."""

from typing import AsyncGenerator

from app import config as cfg
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

_engine = None
_SessionLocal = None


def get_engine():
    global _engine
    if _engine is None:
        url = cfg.DATABASE_URL
        if url.startswith("postgres://"):
            url = url.replace("postgres://", "postgresql+psycopg://", 1)
        elif url.startswith("postgresql://"):
            url = url.replace("postgresql://", "postgresql+psycopg://", 1)
        elif "postgresql+asyncpg://" in url:
            url = url.replace("postgresql+asyncpg://", "postgresql+psycopg://", 1)
        _engine = create_async_engine(url, echo=False)
    return _engine


def get_session_maker():
    global _SessionLocal
    if _SessionLocal is None:
        _SessionLocal = async_sessionmaker(
            get_engine(),
            expire_on_commit=False,
            class_=AsyncSession,
        )
    return _SessionLocal


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    SessionLocal = get_session_maker()
    async with SessionLocal() as session:
        yield session


async def close_db():
    global _engine, _SessionLocal
    if _engine:
        await _engine.dispose()
        _engine = None
        _SessionLocal = None
