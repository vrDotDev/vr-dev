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

from fastapi import APIRouter, Depends, FastAPI, HTTPException, Query, Request
from fastapi.responses import StreamingResponse

from vrdev.core.compose import compose
from vrdev.core.ensemble import EnsembleVerifier
from vrdev.core.export import export_jsonl_lines
from vrdev.core.registry import get_verifier, list_verifiers
from vrdev.core.types import PolicyMode, StepInput, VerificationResult, VerifierInput

from .auth import require_admin_key, require_api_key, require_auth
from .db import (
    close_db,
    get_anchor,
    get_evidence,
    get_latest_anchor,
    get_payments_by_address,
    get_quota,
    get_revenue_summary,
    get_usage,
    init_db,
    list_evidence,
    list_evidence_since,
    set_quota,
    store_anchor,
    store_evidence,
    update_evidence_batch_id,
)
from .rate_limit import check_rate_limit
from .schemas import (
    BatchResultItem,
    BatchVerifyRequest,
    BatchVerifyResponse,
    ComposeRequest,
    ComposeResponse,
    EnsembleRequest,
    EnsembleResponse,
    EvidenceListResponse,
    EvidenceResponse,
    ExportRequest,
    ExportResponse,
    HealthResponse,
    KeyItem,
    KeysResponse,
    PaymentItem,
    PaymentsResponse,
    PricingResponse,
    PricingTierItem,
    ProofResponse,
    QuotaItem,
    QuotaResponse,
    ResultItem,
    RevenueItem,
    RevenueResponse,
    SetQuotaRequest,
    StreamVerifyRequest,
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

    # Start anchor batch loop if signing key is configured
    anchor_task = None
    anchor_interval = float(os.environ.get("VR_ANCHOR_INTERVAL_HOURS", "24"))
    if os.environ.get("VR_ANCHOR_PRIVATE_KEY"):
        from .anchor import anchor_loop
        anchor_task = asyncio.create_task(anchor_loop(interval_hours=anchor_interval))

    yield

    if anchor_task:
        anchor_task.cancel()
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


async def _record_payment(request: Request, result: object) -> None:
    """Record an x402 payment if one was used for this request."""
    payment = getattr(request.state, "payment", None)
    if payment is None:
        return
    artifact_hash = None
    results = getattr(result, "results", None)
    if results and hasattr(results[0], "artifact_hash"):
        artifact_hash = results[0].artifact_hash or None
    try:
        from .payments.x402 import get_x402_provider
        await get_x402_provider().record_charge(payment, artifact_hash)
    except Exception:
        pass  # payment recording is best-effort


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
            repair_hints=r.repair_hints,
            retryable=r.retryable,
            suggested_action=r.suggested_action,
            step_rewards=r.step_rewards,
            signature=r.signature,
            signing_key_id=r.signing_key_id,
        )
        for r in results
    ]


# ══════════════════════════════════════════════════════════════════════════════
# /v1/ Router — all first-class endpoints
# ══════════════════════════════════════════════════════════════════════════════

v1 = APIRouter(prefix="/v1", tags=["v1"])


@v1.post("/verify", response_model=VerifyResponse, dependencies=_AUTH_DEPS)
async def verify_v1(
    request: Request,
    body: VerifyRequest,
    auth_id: str = Depends(require_auth),
) -> VerifyResponse:
    result = await _do_verify(body)
    await _record_payment(request, result)
    return result


@v1.get("/evidence/{artifact_hash}", response_model=EvidenceResponse, dependencies=_AUTH_DEPS)
async def evidence_v1(
    artifact_hash: str,
    auth_id: str = Depends(require_auth),
) -> EvidenceResponse:
    return await _do_evidence(artifact_hash)


@v1.get("/evidence", response_model=EvidenceListResponse, dependencies=_AUTH_DEPS)
async def evidence_list_v1(
    auth_id: str = Depends(require_auth),
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
    request: Request,
    body: ComposeRequest,
    auth_id: str = Depends(require_auth),
) -> ComposeResponse:
    result = await _do_compose(body)
    await _record_payment(request, result)
    return result


@v1.get("/verifiers", response_model=VerifiersResponse, dependencies=_AUTH_DEPS)
async def list_verifiers_v1(
    auth_id: str = Depends(require_auth),
) -> VerifiersResponse:
    return VerifiersResponse(verifiers=list_verifiers())


@v1.post("/export", response_model=ExportResponse, dependencies=_AUTH_DEPS)
async def export_v1(
    body: ExportRequest,
    auth_id: str = Depends(require_auth),
) -> ExportResponse:
    return await _do_export(body)


@v1.get("/usage", response_model=UsageResponse, dependencies=_AUTH_DEPS)
async def usage_v1(
    auth_id: str = Depends(require_auth),
) -> UsageResponse:
    return await _do_usage()


@v1.post("/batch", response_model=BatchVerifyResponse, dependencies=_AUTH_DEPS)
async def batch_verify_v1(
    request: Request,
    body: BatchVerifyRequest,
    auth_id: str = Depends(require_auth),
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
    result = BatchVerifyResponse(items=items)
    await _record_payment(request, result)
    return result


# ── Ensemble endpoint (C4 — experimental) ─────────────────────────────────────────


@v1.post("/ensemble", response_model=EnsembleResponse, dependencies=_AUTH_DEPS)
async def ensemble_verify_v1(
    request: Request,
    body: EnsembleRequest,
    auth_id: str = Depends(require_auth),
) -> EnsembleResponse:
    """Run a verifier multiple times and merge via consensus voting."""
    verifier_id = body.verifier_id
    if not verifier_id.startswith("vr/"):
        verifier_id = f"vr/{verifier_id}"

    def factory():
        return get_verifier(verifier_id)

    valid_strategies = {"majority", "unanimous", "any_pass", "weighted"}
    if body.strategy not in valid_strategies:
        raise HTTPException(status_code=400, detail=f"strategy must be one of {valid_strategies}")

    num = max(1, min(body.num_instances, 10))
    threshold = max(0.0, min(body.consensus_threshold, 1.0))

    ens = EnsembleVerifier(
        verifier_factory=factory,
        num_instances=num,
        consensus_threshold=threshold,
        strategy=body.strategy,
    )

    inp = VerifierInput(
        completions=body.completions,
        ground_truth=body.ground_truth,
        context=body.context or {},
    )
    raw = await ens.async_verify(inp)

    def to_items(results: list[VerificationResult]) -> list[ResultItem]:
        return [
            ResultItem(
                verdict=r.verdict.value,
                score=r.score,
                tier=r.tier.value,
                breakdown=r.breakdown,
                evidence=r.evidence,
                artifact_hash=r.artifact_hash,
                passed=r.verdict.value == "PASS",
                repair_hints=r.repair_hints,
                retryable=r.retryable,
                suggested_action=r.suggested_action,
            )
            for r in results
        ]

    items = to_items(raw)
    meta = {
        "strategy": body.strategy,
        "num_instances": num,
        "consensus_threshold": threshold,
    }

    result = EnsembleResponse(results=items, ensemble_metadata=meta)
    await _record_payment(request, result)
    return result


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
        api_key=quota.api_key_id,
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
        api_key=quota.api_key_id,
        daily_limit=quota.daily_limit,
        monthly_limit=quota.monthly_limit,
    ))


# ── SSE stream endpoint ─────────────────────────────────────────────────────────


@v1.post("/verify/stream", dependencies=_AUTH_DEPS)
async def stream_verify_v1(
    body: StreamVerifyRequest,
    auth_id: str = Depends(require_auth),
):
    """Stream step-level verification results via SSE."""
    try:
        verifiers = [get_verifier(vid) for vid in body.verifier_ids]
    except Exception:
        raise HTTPException(status_code=422, detail="One or more verifier IDs not found")

    mode = PolicyMode(body.policy_mode)
    composed = compose(verifiers, require_hard=body.require_hard, policy_mode=mode)

    steps = [
        StepInput(
            step_index=s.step_index,
            completions=s.completions,
            ground_truth=s.ground_truth,
            context=s.context,
            is_terminal=s.is_terminal,
        )
        for s in body.steps
    ]

    async def event_generator():
        trajectory = composed.verify_trajectory(steps)
        for step_results in trajectory:
            for r in results_to_items(step_results):
                yield f"data: {json.dumps(r)}\n\n"
        yield "data: {\"done\": true}\n\n"

    def results_to_items(results: list[VerificationResult]) -> list[dict]:
        return [
            ResultItem(
                verdict=r.verdict.value,
                score=r.score,
                tier=r.tier.value if hasattr(r.tier, "value") else str(r.tier),
                breakdown=r.breakdown,
                evidence=r.evidence,
                artifact_hash=r.artifact_hash or "",
                passed=r.passed,
                repair_hints=r.repair_hints,
                retryable=r.retryable,
                suggested_action=r.suggested_action,
                step_rewards=r.step_rewards,
                signature=r.signature,
                signing_key_id=r.signing_key_id,
            ).model_dump()
            for r in results
        ]

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


# ── Proof endpoint ───────────────────────────────────────────────────────────────


@v1.get("/evidence/{artifact_hash}/proof", response_model=ProofResponse, dependencies=_AUTH_DEPS)
async def evidence_proof_v1(
    artifact_hash: str,
    auth_id: str = Depends(require_auth),
) -> ProofResponse:
    """Return Merkle inclusion proof for anchored evidence."""
    record = await get_evidence(artifact_hash)
    if record is None:
        raise HTTPException(status_code=404, detail="Evidence not found")
    if record.batch_id is None:
        raise HTTPException(status_code=404, detail="Evidence not yet anchored")

    anchor = await get_anchor(record.batch_id)
    if anchor is None:
        raise HTTPException(status_code=404, detail="Anchor record not found")

    # Re-build Merkle tree for the batch to get the proof
    from datetime import datetime, timezone
    from .merkle import build_merkle_tree, get_inclusion_proof, verify_inclusion

    batch_evidence = await list_evidence_since(
        datetime.min.replace(tzinfo=timezone.utc)
    )
    batch_hashes = [
        e.artifact_hash for e in batch_evidence if e.batch_id == record.batch_id
    ]

    if not batch_hashes:
        raise HTTPException(status_code=404, detail="No evidence in batch")

    tree = build_merkle_tree(batch_hashes)
    proof = get_inclusion_proof(tree, artifact_hash)
    verified = verify_inclusion(anchor.merkle_root, artifact_hash, proof)

    return ProofResponse(
        artifact_hash=artifact_hash,
        merkle_root=anchor.merkle_root,
        proof=[{"sibling": s, "direction": d} for s, d in proof],
        batch_id=anchor.batch_id,
        tx_hash=anchor.tx_hash,
        chain=anchor.chain,
        verified=verified,
    )


# ── Keys endpoint ────────────────────────────────────────────────────────────────


@v1.get("/keys", response_model=KeysResponse)
async def keys_v1() -> KeysResponse:
    """Return active signing public keys (no auth required)."""
    keys: list[KeyItem] = []
    try:
        from .signing import load_signing_key, public_key_pem, _compute_key_id
        sk = load_signing_key()
        if sk:
            pub = sk.public_key()
            keys.append(KeyItem(
                key_id=_compute_key_id(pub),
                public_key_pem=public_key_pem(pub),
            ))
    except Exception:
        pass
    return KeysResponse(keys=keys)


# ── Anchor admin endpoint ────────────────────────────────────────────────────────


@v1.post("/anchor")
async def anchor_v1(
    admin_key: str = Depends(require_admin_key),
):
    """Trigger an on-demand anchor batch (admin only)."""
    from .anchor import anchor_batch
    result = await anchor_batch()
    if result is None:
        return {"status": "no_evidence", "message": "No un-anchored evidence to anchor"}
    return {"status": "anchored", **result}


# ── Payment / Pricing endpoints ──────────────────────────────────────────────────


@v1.get("/pricing", response_model=PricingResponse)
async def pricing_v1() -> PricingResponse:
    """Return per-tier USDC pricing (no auth required)."""
    from .payments import COMPOSE_SURCHARGE, TIER_PRICES
    from .payments.x402 import _is_x402_enabled

    tiers = [
        PricingTierItem(tier=t, price_usdc=float(p))
        for t, p in TIER_PRICES.items()
    ]
    return PricingResponse(
        tiers=tiers,
        compose_surcharge_usdc=float(COMPOSE_SURCHARGE),
        x402_enabled=_is_x402_enabled(),
    )


@v1.get("/payments/{address}", response_model=PaymentsResponse, dependencies=_AUTH_DEPS)
async def payments_v1(
    address: str,
    auth_id: str = Depends(require_auth),
    limit: int = Query(100, ge=1, le=1000),
) -> PaymentsResponse:
    """Return payment history for a wallet address."""
    records = await get_payments_by_address(address, limit=limit)
    items = [
        PaymentItem(
            payer_address=r.payer_address,
            amount_usdc=float(r.amount_usdc),
            tx_hash=r.tx_hash,
            verification_id=r.verification_id,
            endpoint=r.endpoint,
            tier=r.tier,
            provider=r.provider,
            created_at=r.created_at.isoformat(),
        )
        for r in records
    ]
    return PaymentsResponse(payments=items, count=len(items))


@v1.get("/revenue", response_model=RevenueResponse)
async def revenue_v1(
    admin_key: str = Depends(require_admin_key),
) -> RevenueResponse:
    """Return revenue summary (admin only)."""
    rows = await get_revenue_summary()
    items = [
        RevenueItem(
            provider=r["provider"],
            tier=r["tier"],
            tx_count=r["tx_count"],
            total_usdc=r["total_usdc"],
        )
        for r in rows
    ]
    return RevenueResponse(revenue=items)


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

    # Sign evidence if signing key is configured
    try:
        from .signing import load_signing_key, sign_evidence, _compute_key_id
        signing_key = load_signing_key()
        if signing_key:
            key_id = _compute_key_id(signing_key.public_key())
            for r in results:
                if r.artifact_hash:
                    r.signature = sign_evidence(r.artifact_hash, signing_key)
                    r.signing_key_id = key_id
    except Exception:
        pass  # Signing is best-effort

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
                    signature=r.signature,
                    signing_key_id=r.signing_key_id,
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
