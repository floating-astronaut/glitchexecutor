"""
Trade-admin proxy.

The admin dashboard browser must never see TRADE_ADMIN_API_SECRET. The
SPA hits these JWT-protected endpoints on this router; the router
forwards each call to glitch-trade-api (127.0.0.1:3112) with the
X-Admin-Secret header injected from this process's own env.

Powers the Trade · Business surface (Revenue / Users / Subscriptions)
in glitch-admin-dashboard. Trade-api lives in a separate FastAPI
service so its DB + lifecycle stays independent; this router only
proxies, no business logic.

Endpoints (1:1 with trade-api /v1/admin/*):
    GET /api/trade-admin/metrics
    GET /api/trade-admin/users?limit=&offset=&q=
    GET /api/trade-admin/subscriptions?status=&limit=
"""
import logging
import os
from typing import Optional

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query

from auth import get_current_user

logger = logging.getLogger("trade_admin")

router = APIRouter()

TRADE_API_URL = os.environ.get("TRADE_API_URL", "http://127.0.0.1:3112").rstrip("/")
TRADE_ADMIN_API_SECRET = os.environ.get("TRADE_ADMIN_API_SECRET", "")

_TIMEOUT = httpx.Timeout(10.0, connect=5.0)


def _headers() -> dict:
    if not TRADE_ADMIN_API_SECRET:
        # Fail closed — surface the misconfig loudly rather than passing an
        # empty header that trade-api would 401 on.
        raise HTTPException(
            status_code=503,
            detail="trade-admin proxy not configured (TRADE_ADMIN_API_SECRET missing)",
        )
    return {"x-admin-secret": TRADE_ADMIN_API_SECRET}


async def _get(path: str, params: Optional[dict] = None) -> dict:
    url = f"{TRADE_API_URL}{path}"
    async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
        try:
            r = await client.get(url, params=params, headers=_headers())
        except httpx.HTTPError as e:
            logger.exception("trade-admin proxy GET %s failed", path)
            raise HTTPException(status_code=502, detail=f"trade-api unreachable: {e}") from e
    if r.status_code >= 500:
        raise HTTPException(status_code=502, detail=f"trade-api {r.status_code}")
    if r.status_code >= 400:
        # Forward 4xx so the UI can surface a clear error.
        raise HTTPException(status_code=r.status_code, detail=r.text)
    return r.json()


# ── Endpoints ───────────────────────────────────────────────────────────────


@router.get("/metrics")
async def metrics(user=Depends(get_current_user)):
    """Trade business headline metrics — MRR, paid/free split, churn, conv."""
    return await _get("/v1/admin/metrics")


@router.get("/users")
async def list_users(
    user=Depends(get_current_user),
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
    q: str = Query("", description="Optional substring match against email"),
):
    """Paginated user list with sub state + activity counts."""
    params: dict = {"limit": limit, "offset": offset}
    if q:
        params["q"] = q
    return await _get("/v1/admin/users", params=params)


@router.get("/subscriptions")
async def list_subscriptions(
    user=Depends(get_current_user),
    status: str = Query("", description="Optional exact status filter"),
    limit: int = Query(200, ge=1, le=1000),
):
    """All subscription rows with optional status filter."""
    params: dict = {"limit": limit}
    if status:
        params["status"] = status
    return await _get("/v1/admin/subscriptions", params=params)
