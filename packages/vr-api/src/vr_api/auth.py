"""API-key authentication dependency.

Validates keys by SHA-256 hashing and looking up the hash in the shared
NeonDB ``api_keys`` table (written by the Next.js frontend).

Fallback behaviour:
- ``VR_API_KEYS`` env var (comma-separated) is checked first for admin/CI keys.
- When *neither* env var keys nor DB are available, auth is disabled (dev mode).
"""

from __future__ import annotations

import hashlib
import os
from datetime import datetime, timezone

from fastapi import HTTPException, Request, Security
from fastapi.security import APIKeyHeader
from sqlalchemy import text

from .db import get_session_factory

_api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)


def _get_env_keys() -> set[str]:
    """Return admin/CI keys from the ``VR_API_KEYS`` env var."""
    raw = os.environ.get("VR_API_KEYS", "")
    return {k.strip() for k in raw.split(",") if k.strip()}


def _hash_key(raw: str) -> str:
    """SHA-256 hash matching the Next.js key-actions helper."""
    return hashlib.sha256(raw.encode()).hexdigest()


async def _validate_db_key(api_key: str) -> bool:
    """Check the key hash against the ``api_keys`` table and bump last_used_at."""
    try:
        factory = get_session_factory()
    except RuntimeError:
        return False  # DB not initialised — skip DB check

    key_hash = _hash_key(api_key)
    try:
        async with factory() as session:
            row = await session.execute(
                text(
                    "SELECT id FROM api_keys "
                    "WHERE key_hash = :h AND revoked_at IS NULL "
                    "LIMIT 1"
                ),
                {"h": key_hash},
            )
            result = row.first()
            if result is None:
                return False

            await session.execute(
                text("UPDATE api_keys SET last_used_at = :now WHERE id = :id"),
                {"now": datetime.now(timezone.utc).replace(tzinfo=None), "id": str(result[0])},
            )
            await session.commit()
            return True
    except Exception:
        return False  # Table missing (SQLite tests) or DB error — skip


async def require_api_key(
    api_key: str | None = Security(_api_key_header),
) -> str:
    """FastAPI dependency that enforces API-key auth.

    Returns the validated key, or ``"dev"`` when auth is disabled.
    """
    env_keys = _get_env_keys()

    # 1. Check env var keys (admin / CI)
    if env_keys and api_key and api_key in env_keys:
        return api_key

    # 2. Check NeonDB api_keys table
    if api_key and await _validate_db_key(api_key):
        return api_key

    # 3. Dev mode — no env keys configured and DB has no keys table yet
    if not env_keys:
        return "dev"

    raise HTTPException(status_code=401, detail="Invalid or missing API key")


async def require_admin_key(
    api_key: str | None = Security(_api_key_header),
) -> str:
    """FastAPI dependency that enforces admin-only access.

    Reads the expected admin key from ``VR_ADMIN_KEY`` env var.
    Returns the validated key, or ``"dev"`` when the var is unset.
    """
    admin_key = os.environ.get("VR_ADMIN_KEY", "")
    if not admin_key:
        return "dev"  # admin auth disabled (development mode)
    if api_key != admin_key:
        raise HTTPException(status_code=403, detail="Admin access required")
    return api_key


async def require_auth(request: Request) -> str:
    """Dual-auth dependency: API key **or** x402 USDC payment.

    Returns the authenticated identity:
    - Raw API key string for key-based auth
    - ``"x402:{address}"`` for x402 payment
    - ``"dev"`` when auth is disabled (no env keys configured)

    Raises 402 when x402 is enabled but no valid payment is provided.
    Raises 401 when key auth fails and x402 is disabled.
    """
    env_keys = _get_env_keys()

    # 1. Try API key auth (X-API-Key header) ───────────────────────────────
    api_key = request.headers.get("X-API-Key")
    if api_key:
        if env_keys and api_key in env_keys:
            return api_key
        if await _validate_db_key(api_key):
            return api_key

    # 2. Try x402 payment (X-PAYMENT header) ───────────────────────────────
    from .payments.x402 import _is_x402_enabled, get_x402_provider

    if _is_x402_enabled():
        provider = get_x402_provider()
        payment = await provider.check_payment(request)
        if payment:
            request.state.payment = payment
            return f"x402:{payment.payer_address}"

        # x402 enabled but no valid payment → 402 Payment Required
        from .payments import get_price_for_tier

        headers = provider.create_payment_requirement(
            endpoint=str(request.url.path),
            tier="SOFT",
            amount=get_price_for_tier("SOFT"),
        )
        raise HTTPException(
            status_code=402, detail="Payment required", headers=headers,
        )

    # 3. Dev mode — no env keys configured → allow unauthenticated access
    if not env_keys:
        return "dev"

    raise HTTPException(status_code=401, detail="Invalid or missing API key")
