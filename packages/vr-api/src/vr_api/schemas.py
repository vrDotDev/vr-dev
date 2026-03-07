"""Pydantic request / response schemas for the verification API."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel


# ── Requests ─────────────────────────────────────────────────────────────────


class VerifyRequest(BaseModel):
    verifier_id: str
    completions: list[str]
    ground_truth: dict[str, Any]
    context: dict[str, Any] | None = None


class ComposeRequest(BaseModel):
    verifier_ids: list[str]
    completions: list[str]
    ground_truth: dict[str, Any]
    context: dict[str, Any] | None = None
    require_hard: bool = True
    policy_mode: str = "fail_closed"


class ExportRequest(BaseModel):
    verifier_id: str
    completions: list[str]
    ground_truth: dict[str, Any]
    context: dict[str, Any] | None = None
    extra: dict[str, Any] | None = None


# ── Responses ────────────────────────────────────────────────────────────────


class ResultItem(BaseModel):
    verdict: str
    score: float
    tier: str
    breakdown: dict[str, float]
    evidence: dict[str, Any]
    artifact_hash: str
    passed: bool
    step_rewards: list[float] | None = None


class VerifyResponse(BaseModel):
    results: list[ResultItem]


class ComposeResponse(BaseModel):
    results: list[ResultItem]


class VerifiersResponse(BaseModel):
    verifiers: list[str]


class ExportResponse(BaseModel):
    lines: list[str]
    count: int


class HealthResponse(BaseModel):
    status: str
    version: str


class EvidenceResponse(BaseModel):
    artifact_hash: str
    verifier_id: str
    verdict: str
    score: float
    evidence: dict[str, Any]
    created_at: str


class UsageSummaryItem(BaseModel):
    api_key: str
    request_count: int
    avg_latency_ms: float


class UsageResponse(BaseModel):
    usage: list[UsageSummaryItem]


# ── Batch ────────────────────────────────────────────────────────────────────


class BatchVerifyRequest(BaseModel):
    items: list[VerifyRequest]


class BatchResultItem(BaseModel):
    verifier_id: str
    results: list[ResultItem]
    error: str | None = None


class BatchVerifyResponse(BaseModel):
    items: list[BatchResultItem]


# ── Evidence list ────────────────────────────────────────────────────────────


class EvidenceListResponse(BaseModel):
    evidence: list[EvidenceResponse]
    count: int


# ── Quota ────────────────────────────────────────────────────────────────────


class QuotaItem(BaseModel):
    api_key: str
    daily_limit: int
    monthly_limit: int


class QuotaResponse(BaseModel):
    quota: QuotaItem


class SetQuotaRequest(BaseModel):
    daily_limit: int = 1000
    monthly_limit: int = 10000
