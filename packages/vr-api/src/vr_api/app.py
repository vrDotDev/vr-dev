"""FastAPI application — routes delegate to ``vrdev`` core, zero verifier logic here.

All routes live under ``/v1/`` (except ``/health``).
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
from contextlib import asynccontextmanager
from typing import Optional

import structlog

from fastapi import APIRouter, Depends, FastAPI, HTTPException, Query

from vrdev.core.compose import compose
from vrdev.core.export import export_jsonl_lines
from vrdev.core.registry import get_verifier, list_verifiers
from vrdev.core.types import PolicyMode, VerificationResult, VerifierInput

from .auth import require_admin_key, require_api_key
from .db import (
    close_db,
    get_evidence,
    get_quota,
    get_usage,
    init_db,
    list_evidence,
    set_quota,
    store_evidence,
)
from .rate_limit import check_rate_limit
from .schemas import (
    BatchResultItem,
    BatchVerifyRequest,
    BatchVerifyResponse,
    ComposeRequest,
    ComposeResponse,
    EvidenceListResponse,
    EvidenceResponse,
    ExportRequest,
    ExportResponse,
    HealthResponse,
    QuotaItem,
    QuotaResponse,
    ResultItem,
    SetQuotaRequest,
    UsageResponse,
    UsageSummaryItem,
    VerifiersResponse,
    VerifyRequest,
    VerifyResponse,
)
from .usage import UsageMiddleware, check_quota

logger = structlog.get_logger(__name__)


# ── Lifespan ─────────────────────────────────────────────────────────────────────


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Initialise the database on startup, close on shutdown."""
    from .cleanup_worker import cleanup_loop
    from .observability import configure_logging, configure_tracing
    from .rate_limit import close_bucket

    configure_logging(json_output=os.environ.get("VR_LOG_JSON", "1") == "1")
    configure_tracing(app)
    await init_db()

    # Start evidence TTL cleanup as background task (can also run standalone
    # via ``python -m vr_api.cleanup_worker``)
    ttl_days = int(os.environ.get("VR_EVIDENCE_TTL_DAYS", "90"))
    interval_hours = float(os.environ.get("VR_CLEANUP_INTERVAL_HOURS", "6"))
    cleanup_task = None
    if ttl_days > 0:
        cleanup_task = asyncio.create_task(
            cleanup_loop(ttl_days=ttl_days, interval_hours=interval_hours)
        )

    yield

    if cleanup_task:
        cleanup_task.cancel()
    await close_bucket()
    await close_db()


app = FastAPI(
    title="vr-api",
    description="Hosted verification service for vr.dev",
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(UsageMiddleware)


# ── Helpers ──────────────────────────────────────────────────────────────────────

_AUTH_DEPS = [Depends(check_rate_limit), Depends(check_quota)]


def _to_result_items(results: list[VerificationResult]) -> list[ResultItem]:
    return [
        ResultItem(
            verdict=r.verdict.value,
            score=r.score,
            tier=r.tier.value if hasattr(r.tier, "value") else str(r.tier),
            breakdown=r.breakdown,
            evidence=r.evidence,
            artifact_hash=r.artifact_hash or "",
            passed=r.passed,
            step_rewards=r.step_rewards,
        )
        for r in results
    ]


# ══════════════════════════════════════════════════════════════════════════════
# /v1/ Router — all first-class endpoints
# ══════════════════════════════════════════════════════════════════════════════

v1 = APIRouter(prefix="/v1", tags=["v1"])


@v1.post("/verify", response_model=VerifyResponse, dependencies=_AUTH_DEPS)
async def verify_v1(
    body: VerifyRequest,
    api_key: str = Depends(require_api_key),
) -> VerifyResponse:
    return await _do_verify(body)


@v1.get("/evidence/{artifact_hash}", response_model=EvidenceResponse, dependencies=_AUTH_DEPS)
async def evidence_v1(
    artifact_hash: str,
    api_key: str = Depends(require_api_key),
) -> EvidenceResponse:
    return await _do_evidence(artifact_hash)


@v1.get("/evidence", response_model=EvidenceListResponse, dependencies=_AUTH_DEPS)
async def evidence_list_v1(
    api_key: str = Depends(require_api_key),
    verifier_id: Optional[str] = Query(None),
    limit: int = Query(100, ge=1, le=1000),
) -> EvidenceListResponse:
    records = await list_evidence(verifier_id=verifier_id, limit=limit)
    items = [
        EvidenceResponse(
            artifact_hash=r.artifact_hash,
            verifier_id=r.verifier_id,
            verdict=r.verdict,
            score=r.score,
            evidence=json.loads(r.evidence_json),
            created_at=r.created_at.isoformat(),
        )
        for r in records
    ]
    return EvidenceListResponse(evidence=items, count=len(items))


@v1.post("/compose", response_model=ComposeResponse, dependencies=_AUTH_DEPS)
async def compose_v1(
    body: ComposeRequest,
    api_key: str = Depends(require_api_key),
) -> ComposeResponse:
    return await _do_compose(body)


@v1.get("/verifiers", response_model=VerifiersResponse, dependencies=_AUTH_DEPS)
async def list_verifiers_v1(
    api_key: str = Depends(require_api_key),
) -> VerifiersResponse:
    return VerifiersResponse(verifiers=list_verifiers())


@v1.post("/export", response_model=ExportResponse, dependencies=_AUTH_DEPS)
async def export_v1(
    body: ExportRequest,
    api_key: str = Depends(require_api_key),
) -> ExportResponse:
    return await _do_export(body)


@v1.get("/usage", response_model=UsageResponse, dependencies=_AUTH_DEPS)
async def usage_v1(
    api_key: str = Depends(require_api_key),
) -> UsageResponse:
    return await _do_usage()


@v1.post("/batch", response_model=BatchVerifyResponse, dependencies=_AUTH_DEPS)
async def batch_verify_v1(
    body: BatchVerifyRequest,
    api_key: str = Depends(require_api_key),
) -> BatchVerifyResponse:
    """Verify multiple items concurrently."""
    tasks = [_do_verify_single(item) for item in body.items]
    results = await asyncio.gather(*tasks, return_exceptions=True)
    items: list[BatchResultItem] = []
    for req, res in zip(body.items, results):
        if isinstance(res, Exception):
            items.append(BatchResultItem(
                verifier_id=req.verifier_id, results=[], error=str(res),
            ))
        else:
            items.append(BatchResultItem(
                verifier_id=req.verifier_id, results=res.results,
            ))
    return BatchVerifyResponse(items=items)


# ── Quota admin endpoints (VR_ADMIN_KEY gated) ────────────────────────────────────────

@v1.get("/quota/{api_key}", response_model=QuotaResponse)
async def get_quota_v1(
    api_key: str,
    admin_key: str = Depends(require_admin_key),
) -> QuotaResponse:
    quota = await get_quota(api_key)
    if quota is None:
        raise HTTPException(status_code=404, detail=f"No quota for key: {api_key}")
    return QuotaResponse(quota=QuotaItem(
        api_key=quota.api_key,
        daily_limit=quota.daily_limit,
        monthly_limit=quota.monthly_limit,
    ))


@v1.put("/quota/{api_key}", response_model=QuotaResponse)
async def set_quota_v1(
    api_key: str,
    body: SetQuotaRequest,
    admin_key: str = Depends(require_admin_key),
) -> QuotaResponse:
    quota = await set_quota(api_key, body.daily_limit, body.monthly_limit)
    return QuotaResponse(quota=QuotaItem(
        api_key=quota.api_key,
        daily_limit=quota.daily_limit,
        monthly_limit=quota.monthly_limit,
    ))


app.include_router(v1)


# Health (no auth, no rate limit — always bare)
@app.get("/health", response_model=HealthResponse)
async def health() -> HealthResponse:
    return HealthResponse(status="ok", version="1.0.0")


# ══════════════════════════════════════════════════════════════════════════════
# Shared logic (used by both /v1/ and legacy routes)
# ══════════════════════════════════════════════════════════════════════════════


async def _do_verify(body: VerifyRequest) -> VerifyResponse:
    try:
        v = get_verifier(body.verifier_id)
    except Exception:
        raise HTTPException(status_code=404, detail=f"Unknown verifier: {body.verifier_id}")
    inp = VerifierInput(
        completions=body.completions,
        ground_truth=body.ground_truth,
        context=body.context,
    )
    results = await v.async_verify(inp)

    # Record OTel span attributes when tracing is active
    try:
        from opentelemetry import trace as otel_trace

        span = otel_trace.get_current_span()
        if span and span.is_recording():
            span.set_attribute("vr.verifier_id", body.verifier_id)
            if results:
                span.set_attribute("vr.verdict", results[0].verdict.value)
                span.set_attribute("vr.score", results[0].score)
    except ImportError:
        pass

    for r in results:
        if r.artifact_hash:
            try:
                await store_evidence(
                    artifact_hash=r.artifact_hash,
                    verifier_id=body.verifier_id,
                    verdict=r.verdict.value,
                    score=r.score,
                    evidence_json=json.dumps(r.evidence, default=str),
                )
            except Exception:
                pass  # Best-effort evidence storage
    return VerifyResponse(results=_to_result_items(results))


async def _do_verify_single(body: VerifyRequest) -> VerifyResponse:
    """Run a single verify — used by batch endpoint. Exceptions propagate."""
    return await _do_verify(body)


async def _do_evidence(artifact_hash: str) -> EvidenceResponse:
    record = await get_evidence(artifact_hash)
    if record is None:
        raise HTTPException(status_code=404, detail="Evidence not found")
    return EvidenceResponse(
        artifact_hash=record.artifact_hash,
        verifier_id=record.verifier_id,
        verdict=record.verdict,
        score=record.score,
        evidence=json.loads(record.evidence_json),
        created_at=record.created_at.isoformat(),
    )


async def _do_compose(body: ComposeRequest) -> ComposeResponse:
    try:
        verifiers = [get_verifier(vid) for vid in body.verifier_ids]
    except Exception:
        raise HTTPException(status_code=404, detail="One or more verifier IDs not found")
    mode = PolicyMode(body.policy_mode)
    composed = compose(verifiers, require_hard=body.require_hard, policy_mode=mode)
    inp = VerifierInput(
        completions=body.completions,
        ground_truth=body.ground_truth,
        context=body.context,
    )
    results = await composed.async_verify(inp)
    return ComposeResponse(results=_to_result_items(results))


async def _do_export(body: ExportRequest) -> ExportResponse:
    try:
        v = get_verifier(body.verifier_id)
    except Exception:
        raise HTTPException(status_code=404, detail=f"Unknown verifier: {body.verifier_id}")
    inp = VerifierInput(
        completions=body.completions,
        ground_truth=body.ground_truth,
        context=body.context,
    )
    results = await v.async_verify(inp)
    lines = export_jsonl_lines(results, inp, body.verifier_id, extra=body.extra)
    return ExportResponse(lines=lines, count=len(lines))


async def _do_usage() -> UsageResponse:
    rows = await get_usage()
    items = [
        UsageSummaryItem(
            api_key=r["api_key"],
            request_count=r["request_count"],
            avg_latency_ms=r["avg_latency_ms"],
        )
        for r in rows
    ]
    return UsageResponse(usage=items)
