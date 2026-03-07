"""Evidence persistence — append-only storage for verification results.

Uses SQLAlchemy async with PostgreSQL (production) or SQLite (testing).
Connection string is read from ``DATABASE_URL`` env var.
"""

from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import Column, DateTime, Float, Integer, String, Text, delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

# ── ORM model ────────────────────────────────────────────────────────────────


class Base(DeclarativeBase):
    pass


class EvidenceRecord(Base):
    """Append-only evidence row.

    Primary key is the SHA-256 artifact hash produced by the verifier.
    """

    __tablename__ = "evidence_records"

    artifact_hash = Column(String(71), primary_key=True)  # "sha256:" + 64 hex
    verifier_id = Column(String(128), nullable=False, index=True)
    verdict = Column(String(16), nullable=False)
    score = Column(Float, nullable=False)
    evidence_json = Column(Text, nullable=False)  # serialised JSON
    created_at = Column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )


class UsageRecord(Base):
    """Per-request usage tracking row."""

    __tablename__ = "usage_records"

    id = Column(Integer, primary_key=True, autoincrement=True)
    api_key = Column(String(128), nullable=False, index=True)
    endpoint = Column(String(256), nullable=False)
    method = Column(String(8), nullable=False)
    status_code = Column(Integer, nullable=False)
    latency_ms = Column(Integer, nullable=False, default=0)
    created_at = Column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )


class QuotaRecord(Base):
    """Per-key quota limits.

    When a key has no QuotaRecord, it is unrestricted.
    """

    __tablename__ = "quota_records"

    api_key = Column(String(128), primary_key=True)
    daily_limit = Column(Integer, nullable=False, default=1000)
    monthly_limit = Column(Integer, nullable=False, default=10000)
    created_at = Column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )
    updated_at = Column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )


# ── Engine / session factory ─────────────────────────────────────────────────

_engine = None
_session_factory: async_sessionmaker[AsyncSession] | None = None


def _default_url() -> str:
    return os.environ.get(
        "VR_DATABASE_URL",
        os.environ.get("DATABASE_URL", "sqlite+aiosqlite:///:memory:"),
    )


async def init_db(url: str | None = None) -> None:
    """Create the engine, session factory, and tables."""
    global _engine, _session_factory
    db_url = url or _default_url()
    engine_kwargs: dict[str, Any] = {"echo": False}
    if db_url.startswith("postgresql"):
        engine_kwargs.update(pool_size=5, max_overflow=10)
    _engine = create_async_engine(db_url, **engine_kwargs)
    _session_factory = async_sessionmaker(_engine, expire_on_commit=False)
    async with _engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


async def close_db() -> None:
    """Dispose of the engine."""
    global _engine, _session_factory
    if _engine:
        await _engine.dispose()
    _engine = None
    _session_factory = None


def get_session_factory() -> async_sessionmaker[AsyncSession]:
    if _session_factory is None:
        raise RuntimeError("Database not initialised — call init_db() first")
    return _session_factory


# ── CRUD helpers ─────────────────────────────────────────────────────────────


async def store_evidence(
    artifact_hash: str,
    verifier_id: str,
    verdict: str,
    score: float,
    evidence_json: str,
) -> EvidenceRecord:
    """Insert a new evidence record (append-only, ignore duplicates)."""
    factory = get_session_factory()
    async with factory() as session:
        existing = await session.get(EvidenceRecord, artifact_hash)
        if existing is not None:
            return existing
        record = EvidenceRecord(
            artifact_hash=artifact_hash,
            verifier_id=verifier_id,
            verdict=verdict,
            score=score,
            evidence_json=evidence_json,
        )
        session.add(record)
        await session.commit()
        await session.refresh(record)
        return record


async def get_evidence(artifact_hash: str) -> EvidenceRecord | None:
    """Retrieve an evidence record by its artifact hash."""
    factory = get_session_factory()
    async with factory() as session:
        return await session.get(EvidenceRecord, artifact_hash)


async def list_evidence(
    verifier_id: str | None = None,
    limit: int = 100,
) -> list[EvidenceRecord]:
    """List evidence records, optionally filtered by verifier ID."""
    factory = get_session_factory()
    async with factory() as session:
        stmt = select(EvidenceRecord).order_by(
            EvidenceRecord.created_at.desc()
        )
        if verifier_id:
            stmt = stmt.where(EvidenceRecord.verifier_id == verifier_id)
        stmt = stmt.limit(limit)
        result = await session.execute(stmt)
        return list(result.scalars().all())


# ── Evidence TTL cleanup ─────────────────────────────────────────────────────


async def cleanup_expired(ttl_days: int) -> int:
    """Delete evidence records older than *ttl_days*.

    Returns the number of deleted rows.
    """
    if ttl_days <= 0:
        return 0
    factory = get_session_factory()
    cutoff = datetime.now(timezone.utc) - timedelta(days=ttl_days)
    async with factory() as session:
        stmt = delete(EvidenceRecord).where(EvidenceRecord.created_at < cutoff)
        result = await session.execute(stmt)
        await session.commit()
        return result.rowcount  # type: ignore[return-value]


# ── Usage tracking ───────────────────────────────────────────────────────────


async def record_usage(
    api_key: str,
    endpoint: str,
    method: str,
    status_code: int,
    latency_ms: int,
) -> UsageRecord:
    """Insert a usage record for a single API request."""
    factory = get_session_factory()
    async with factory() as session:
        record = UsageRecord(
            api_key=api_key,
            endpoint=endpoint,
            method=method,
            status_code=status_code,
            latency_ms=latency_ms,
        )
        session.add(record)
        await session.commit()
        await session.refresh(record)
        return record


async def get_usage(
    api_key: str | None = None,
    limit: int = 100,
) -> list[dict]:
    """Return per-key usage summary (count + avg latency).

    If *api_key* is given, filter to that key; otherwise return all keys.
    """
    factory = get_session_factory()
    async with factory() as session:
        stmt = (
            select(
                UsageRecord.api_key,
                func.count(UsageRecord.id).label("request_count"),
                func.avg(UsageRecord.latency_ms).label("avg_latency_ms"),
            )
            .group_by(UsageRecord.api_key)
            .order_by(func.count(UsageRecord.id).desc())
            .limit(limit)
        )
        if api_key:
            stmt = stmt.where(UsageRecord.api_key == api_key)
        result = await session.execute(stmt)
        return [
            {
                "api_key": row.api_key,
                "request_count": row.request_count,
                "avg_latency_ms": round(float(row.avg_latency_ms or 0), 1),
            }
            for row in result.all()
        ]


# ── Quota management ─────────────────────────────────────────────────────────


async def get_quota(api_key: str) -> QuotaRecord | None:
    """Retrieve the quota record for an API key (or ``None``)."""
    factory = get_session_factory()
    async with factory() as session:
        return await session.get(QuotaRecord, api_key)


async def set_quota(api_key: str, daily_limit: int, monthly_limit: int) -> QuotaRecord:
    """Create or update the quota for an API key."""
    factory = get_session_factory()
    async with factory() as session:
        existing = await session.get(QuotaRecord, api_key)
        if existing is not None:
            existing.daily_limit = daily_limit
            existing.monthly_limit = monthly_limit
            existing.updated_at = datetime.now(timezone.utc)
            await session.commit()
            await session.refresh(existing)
            return existing
        record = QuotaRecord(
            api_key=api_key,
            daily_limit=daily_limit,
            monthly_limit=monthly_limit,
        )
        session.add(record)
        await session.commit()
        await session.refresh(record)
        return record


async def get_usage_count(api_key: str, since: datetime) -> int:
    """Count requests by *api_key* since the given timestamp."""
    factory = get_session_factory()
    async with factory() as session:
        stmt = (
            select(func.count(UsageRecord.id))
            .where(UsageRecord.api_key == api_key)
            .where(UsageRecord.created_at >= since)
        )
        result = await session.execute(stmt)
        return result.scalar_one()
