"""
Customer-management proxy.

The dashboard browser must never see GROW_FULFILL_SECRET. The browser hits
JWT-protected endpoints on this router; the router forwards each call to
the payment server with the X-Fulfill-Secret header injected.

Source of truth for the buyer ledger remains the payment server
(/opt/glitchexecutor/payment/server.py) which owns the Postgres
`glitch_grow_buyers` table plus Stripe / Razorpay / Codeberg / Discord /
Resend integrations.

In a future phase this router will also surface Edge betting buyers and
Trade subscribers under a single /api/customers surface.
"""
import os
import logging
from typing import Optional

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query, Request

from auth import get_current_user

logger = logging.getLogger("customers")

router = APIRouter()

PAYMENT_SERVICE_URL = os.environ.get("PAYMENT_SERVICE_URL", "http://payment:5002").rstrip("/")
GROW_FULFILL_SECRET = os.environ.get("GROW_FULFILL_SECRET", "")

_TIMEOUT = httpx.Timeout(10.0, connect=5.0)


def _headers() -> dict:
    if not GROW_FULFILL_SECRET:
        # We deliberately fail closed — if the dashboard tries to reach customer
        # data without the secret configured, surface that loudly instead of
        # silently hitting an unauthorised payment-server response.
        raise HTTPException(status_code=503, detail="customers proxy not configured (GROW_FULFILL_SECRET missing)")
    return {"x-fulfill-secret": GROW_FULFILL_SECRET, "content-type": "application/json"}


async def _get(path: str, params: Optional[dict] = None) -> dict:
    url = f"{PAYMENT_SERVICE_URL}{path}"
    async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
        try:
            r = await client.get(url, params=params, headers=_headers())
        except httpx.HTTPError as e:
            logger.exception("customers proxy GET %s failed", path)
            raise HTTPException(status_code=502, detail=f"payment-service unreachable: {e}") from e
    if r.status_code >= 500:
        raise HTTPException(status_code=502, detail=f"payment-service {r.status_code}")
    if r.status_code >= 400:
        # Forward 4xx (e.g. 401/404) so the UI can surface a clear error.
        raise HTTPException(status_code=r.status_code, detail=r.text)
    return r.json()


async def _post(path: str, body: dict) -> dict:
    url = f"{PAYMENT_SERVICE_URL}{path}"
    async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
        try:
            r = await client.post(url, json=body, headers=_headers())
        except httpx.HTTPError as e:
            logger.exception("customers proxy POST %s failed", path)
            raise HTTPException(status_code=502, detail=f"payment-service unreachable: {e}") from e
    if r.status_code >= 500:
        raise HTTPException(status_code=502, detail=f"payment-service {r.status_code}")
    if r.status_code >= 400:
        raise HTTPException(status_code=r.status_code, detail=r.text)
    return r.json()


# ── Buyers ───────────────────────────────────────────────────────────────────

@router.get("/buyers")
async def list_buyers(
    email: Optional[str] = None,
    sku: Optional[str] = None,
    payment_id: Optional[str] = None,
    provider: Optional[str] = Query(None, pattern="^(stripe|razorpay)$"),
    limit: int = Query(50, ge=1, le=500),
    user=Depends(get_current_user),
):
    params: dict = {"limit": limit}
    if email: params["email"] = email
    if sku: params["sku"] = sku
    if payment_id: params["payment_id"] = payment_id
    # provider filter is not yet supported by payment server — apply client-side
    data = await _get("/api/grow/buyers", params=params)
    buyers = data.get("buyers", [])
    if provider:
        buyers = [b for b in buyers if b.get("provider") == provider]
    return {"count": len(buyers), "buyers": buyers}


@router.get("/buyer/{payment_id}")
async def buyer_detail(payment_id: str, user=Depends(get_current_user)):
    return await _get(f"/api/grow/buyer/{payment_id}/detail")


# ── Leads ────────────────────────────────────────────────────────────────────

@router.get("/leads")
async def list_leads(user=Depends(get_current_user)):
    return await _get("/api/grow/leads")


# ── Actions ──────────────────────────────────────────────────────────────────

@router.post("/refund")
async def refund(body: dict, user=Depends(get_current_user)):
    return await _post("/api/grow/refund-buyer", body)


@router.post("/resend-welcome")
async def resend_welcome(body: dict, user=Depends(get_current_user)):
    return await _post("/api/grow/resend-welcome", body)


@router.post("/reinvite-codeberg")
async def reinvite_codeberg(body: dict, user=Depends(get_current_user)):
    return await _post("/api/grow/reinvite-codeberg", body)


@router.post("/note")
async def add_note(body: dict, user=Depends(get_current_user)):
    return await _post("/api/grow/buyer-note", body)
