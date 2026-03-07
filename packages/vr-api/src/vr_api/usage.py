"""Usage tracking middleware and quota enforcement.

Phase 5: read-only tracking via ``UsageMiddleware``.
Phase 6: ``check_quota`` dependency enforces per-key daily/monthly limits
stored in the ``quota_records`` table.
"""

from __future__ import annotations

import time
from datetime import datetime, timedelta, timezone

from fastapi import Depends, HTTPException, Request
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request as StarletteRequest
from starlette.responses import Response

from .auth import require_api_key
from .db import get_quota, get_usage_count, record_usage


class UsageMiddleware(BaseHTTPMiddleware):
    """ASGI middleware that records request metadata to the usage_records table."""

    async def dispatch(
        self, request: StarletteRequest, call_next: RequestResponseEndpoint
    ) -> Response:
        start = time.monotonic()
        response = await call_next(request)
        latency_ms = int((time.monotonic() - start) * 1000)

        # Extract API key (may be absent on /health)
        api_key = request.headers.get("x-api-key", "anonymous")
        endpoint = request.url.path
        method = request.method

        # Fire-and-forget — don't block the response
        try:
            await record_usage(
                api_key=api_key,
                endpoint=endpoint,
                method=method,
                status_code=response.status_code,
                latency_ms=latency_ms,
            )
        except Exception:
            pass  # Never fail the request due to usage tracking

        return response


async def check_quota(
    request: Request,
    api_key: str = Depends(require_api_key),
) -> None:
    """FastAPI dependency — enforces per-key daily/monthly quotas.

    Reads limits from the ``quota_records`` table.  Keys with no record
    are unrestricted.  Returns HTTP 429 with a ``Retry-After`` header
    when a limit is exceeded.
    """
    quota = await get_quota(api_key)
    if quota is None:
        return  # no quota configured → unrestricted

    now = datetime.now(timezone.utc)

    # Daily check
    day_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    daily_count = await get_usage_count(api_key, day_start)
    if daily_count >= quota.daily_limit:
        seconds_left = int((day_start + timedelta(days=1) - now).total_seconds())
        raise HTTPException(
            status_code=429,
            detail=f"Daily quota exceeded ({quota.daily_limit} requests/day)",
            headers={"Retry-After": str(max(1, seconds_left))},
        )

    # Monthly check
    month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    monthly_count = await get_usage_count(api_key, month_start)
    if monthly_count >= quota.monthly_limit:
        # Next month start
        if now.month == 12:
            next_month = now.replace(year=now.year + 1, month=1, day=1,
                                     hour=0, minute=0, second=0, microsecond=0)
        else:
            next_month = now.replace(month=now.month + 1, day=1,
                                     hour=0, minute=0, second=0, microsecond=0)
        seconds_left = int((next_month - now).total_seconds())
        raise HTTPException(
            status_code=429,
            detail=f"Monthly quota exceeded ({quota.monthly_limit} requests/month)",
            headers={"Retry-After": str(max(1, seconds_left))},
        )
