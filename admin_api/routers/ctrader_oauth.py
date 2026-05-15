"""
cTrader Open API OAuth 2.0 — multi-tenant connection flow.

Each SSO user can link one or more of their personal cTrader accounts
(live / demo, multi-broker) to the trade-app via the standard OAuth 2.0
authorization-code flow. Tokens are stored encrypted at rest in the
glitchexecutor Postgres `user_ctrader_connections` table.

Flow (high level)
-----------------
  1. Browser hits  GET  /api/ctrader/oauth/start
        → backend mints a one-shot `state` (HMAC-signed JWT, 10 min TTL),
          returns the cTrader authorize URL.
  2. Browser navigates to that URL → user logs into cTrader → approves.
  3. cTrader 302s back to the configured redirect_uri carrying ?code=&state=.
  4. Browser hits  POST /api/ctrader/oauth/callback  with that code+state.
  5. Backend verifies state, exchanges code for tokens against
     https://openapi.ctrader.com/apps/token, fetches the trader-account
     list, encrypts + persists one row per account, returns the list.
  6. Subsequent  GET  /api/ctrader/connections  reads the user's rows.
  7. DELETE /api/ctrader/connections/{ctid} clears a row (no upstream
     revoke API exists for cTrader; we just stop using the token).

Secrets (env)
-------------
  CTRADER_PUBLIC_CLIENT_ID      — Spotware Open API app, public-facing.
                                  REGISTER A SEPARATE APP from the engine's
                                  internal app so user-token mishandling can
                                  never leak the engine's broker access.
  CTRADER_PUBLIC_CLIENT_SECRET  — paired secret.
  CTRADER_PUBLIC_REDIRECT_URI   — must match what's registered on the app
                                  AND what the SPA navigates to after the
                                  approve step (e.g.
                                  https://trade-app.glitchexecutor.com/oauth/ctrader/callback).
  CTRADER_OAUTH_SCOPE           — default "accounts" (read-only). Set to
                                  "trading" to also place orders.
  ADMIN_JWT_SECRET              — already present; we derive a Fernet key
                                  from it so tokens are encrypted at rest
                                  without introducing a new secret.

NOTE: `CTRADER_PUBLIC_*` is intentionally distinct from the existing
`CTRADER_CLIENT_ID`/`CTRADER_CLIENT_SECRET` used by the ml_collector for
the team's own demo accounts.
"""
from __future__ import annotations

import base64
import hashlib
import logging
import os
import secrets
from datetime import datetime, timedelta, timezone
from typing import Optional

import httpx
from cryptography.fernet import Fernet, InvalidToken
from fastapi import APIRouter, Depends, HTTPException, Query
from jose import JWTError, jwt
from pydantic import BaseModel

from auth import get_current_user
from db import get_pg

logger = logging.getLogger("ctrader_oauth")
router = APIRouter()

# ── Config ───────────────────────────────────────────────────────────────────

CTRADER_AUTHORIZE_URL = "https://openapi.ctrader.com/apps/auth"
CTRADER_TOKEN_URL     = "https://openapi.ctrader.com/apps/token"
# Spotware exposes a small REST surface for listing the trader accounts that
# an access token can see. Used right after exchange to enumerate what we just
# got permission for.
CTRADER_ACCOUNTS_URL  = "https://api.spotware.com/connect/tradingaccounts"

CLIENT_ID     = os.environ.get("CTRADER_PUBLIC_CLIENT_ID", "")
CLIENT_SECRET = os.environ.get("CTRADER_PUBLIC_CLIENT_SECRET", "")
REDIRECT_URI  = os.environ.get(
    "CTRADER_PUBLIC_REDIRECT_URI",
    "https://trade-app.glitchexecutor.com/oauth/ctrader/callback",
)
SCOPE         = os.environ.get("CTRADER_OAUTH_SCOPE", "accounts")

JWT_SECRET = os.environ.get("ADMIN_JWT_SECRET", "changeme-in-production")
STATE_TTL_SECONDS = 600  # 10 minutes


def _fernet() -> Fernet:
    """Derive a Fernet key from ADMIN_JWT_SECRET so we don't carry a separate
    encryption secret in the env. SHA-256 of the JWT secret → first 32 bytes
    → urlsafe-b64. Stable across container restarts as long as the JWT
    secret is stable."""
    digest = hashlib.sha256(JWT_SECRET.encode("utf-8")).digest()
    return Fernet(base64.urlsafe_b64encode(digest))


def _check_configured() -> None:
    if not CLIENT_ID or not CLIENT_SECRET:
        raise HTTPException(
            status_code=503,
            detail=(
                "cTrader OAuth not configured — set CTRADER_PUBLIC_CLIENT_ID "
                "and CTRADER_PUBLIC_CLIENT_SECRET on admin_api"
            ),
        )


# ── State token (CSRF + SSO-binding) ─────────────────────────────────────────

def _mint_state(email: str) -> str:
    """Short-lived JWT bound to the SSO user. We require the same email on
    callback so a stolen `state` from another user doesn't graft an
    attacker's cTrader account onto the victim's SSO."""
    payload = {
        "sub": email,
        "nonce": secrets.token_urlsafe(12),
        "exp": datetime.now(timezone.utc) + timedelta(seconds=STATE_TTL_SECONDS),
    }
    return jwt.encode(payload, JWT_SECRET, algorithm="HS256")


def _verify_state(state: str, email: str) -> None:
    try:
        payload = jwt.decode(state, JWT_SECRET, algorithms=["HS256"])
    except JWTError as exc:
        raise HTTPException(status_code=400, detail=f"invalid or expired state: {exc}")
    if payload.get("sub") != email:
        raise HTTPException(status_code=400, detail="state user mismatch")


# ── DB helpers ──────────────────────────────────────────────────────────────

def _upsert_connection(*, email: str, account: dict, tokens: dict) -> None:
    f = _fernet()
    enc_access  = f.encrypt(tokens["access_token"].encode("utf-8")).decode("ascii")
    enc_refresh = f.encrypt(tokens["refresh_token"].encode("utf-8")).decode("ascii")
    expires_at  = datetime.now(timezone.utc) + timedelta(seconds=int(tokens.get("expires_in", 0)))

    conn = get_pg()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO user_ctrader_connections
                  (sso_email, ctid_trader_account_id, broker_name, account_label,
                   is_live, currency, access_token_enc, refresh_token_enc,
                   access_token_expires_at, scope, last_refreshed_at, revoked_at)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, NOW(), NULL)
                ON CONFLICT (sso_email, ctid_trader_account_id) DO UPDATE
                  SET broker_name             = EXCLUDED.broker_name,
                      account_label           = EXCLUDED.account_label,
                      is_live                 = EXCLUDED.is_live,
                      currency                = EXCLUDED.currency,
                      access_token_enc        = EXCLUDED.access_token_enc,
                      refresh_token_enc       = EXCLUDED.refresh_token_enc,
                      access_token_expires_at = EXCLUDED.access_token_expires_at,
                      scope                   = EXCLUDED.scope,
                      last_refreshed_at       = NOW(),
                      revoked_at              = NULL
                """,
                (
                    email,
                    int(account["ctidTraderAccountId"]),
                    account.get("brokerName"),
                    account.get("accountLabel") or account.get("traderLogin"),
                    bool(account.get("live", False)),
                    account.get("depositCurrency"),
                    enc_access,
                    enc_refresh,
                    expires_at,
                    tokens.get("scope") or SCOPE,
                ),
            )
        conn.commit()
    finally:
        conn.close()


def _list_connections(email: str) -> list[dict]:
    conn = get_pg()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT ctid_trader_account_id, broker_name, account_label,
                       is_live, currency, access_token_expires_at,
                       connected_at, last_refreshed_at
                  FROM user_ctrader_connections
                 WHERE sso_email = %s AND revoked_at IS NULL
                 ORDER BY connected_at DESC
                """,
                (email,),
            )
            rows = cur.fetchall()
    finally:
        conn.close()
    return [
        {
            "ctid_trader_account_id": r["ctid_trader_account_id"],
            "broker_name":            r["broker_name"],
            "account_label":          r["account_label"],
            "is_live":                r["is_live"],
            "currency":               r["currency"],
            "access_token_expires_at": r["access_token_expires_at"].isoformat() if r["access_token_expires_at"] else None,
            "connected_at":           r["connected_at"].isoformat() if r["connected_at"] else None,
            "last_refreshed_at":      r["last_refreshed_at"].isoformat() if r["last_refreshed_at"] else None,
        }
        for r in rows
    ]


def _revoke(email: str, ctid: int) -> bool:
    conn = get_pg()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE user_ctrader_connections SET revoked_at = NOW() "
                "WHERE sso_email = %s AND ctid_trader_account_id = %s AND revoked_at IS NULL",
                (email, ctid),
            )
            updated = cur.rowcount
        conn.commit()
    finally:
        conn.close()
    return updated > 0


# ── Endpoints ───────────────────────────────────────────────────────────────

class StartResponse(BaseModel):
    authorize_url: str
    state: str
    redirect_uri: str
    scope: str


@router.get("/oauth/start", response_model=StartResponse)
def oauth_start(user=Depends(get_current_user)):
    """Returns the cTrader authorize URL the SPA should send the user to.

    The browser MAY follow this directly (window.location), or render it
    behind a button — we don't 302 server-side because the SPA wants to
    surface the click + analytics before leaving the page.
    """
    _check_configured()
    state = _mint_state(user["email"])
    qs = httpx.QueryParams({
        "client_id":    CLIENT_ID,
        "redirect_uri": REDIRECT_URI,
        "scope":        SCOPE,
        "response_type": "code",
        "state":        state,
    })
    return StartResponse(
        authorize_url=f"{CTRADER_AUTHORIZE_URL}?{qs}",
        state=state,
        redirect_uri=REDIRECT_URI,
        scope=SCOPE,
    )


class CallbackBody(BaseModel):
    code: str
    state: str


@router.post("/oauth/callback")
async def oauth_callback(body: CallbackBody, user=Depends(get_current_user)):
    """Exchange the authorization code for tokens, enumerate accounts,
    persist one row per account, return the list."""
    _check_configured()
    _verify_state(body.state, user["email"])

    # 1) Exchange code → token
    async with httpx.AsyncClient(timeout=15.0) as client:
        try:
            tr = await client.post(
                CTRADER_TOKEN_URL,
                data={
                    "grant_type":    "authorization_code",
                    "code":          body.code,
                    "redirect_uri":  REDIRECT_URI,
                    "client_id":     CLIENT_ID,
                    "client_secret": CLIENT_SECRET,
                },
                headers={"Accept": "application/json"},
            )
        except httpx.HTTPError as exc:
            raise HTTPException(status_code=502, detail=f"token endpoint unreachable: {exc}")
    if tr.status_code >= 400:
        raise HTTPException(status_code=tr.status_code, detail=f"cTrader token exchange failed: {tr.text}")
    tokens = tr.json() or {}
    if "access_token" not in tokens:
        raise HTTPException(status_code=502, detail=f"cTrader returned no access_token: {tokens}")

    # 2) Enumerate the trader accounts this token sees
    async with httpx.AsyncClient(timeout=15.0) as client:
        try:
            # Spotware's /connect/tradingaccounts ignores Bearer headers —
            # the access token must be passed as ?oauth_token=… query param.
            ar = await client.get(
                CTRADER_ACCOUNTS_URL,
                params={"oauth_token": tokens["access_token"]},
                headers={"Accept": "application/json"},
            )
        except httpx.HTTPError as exc:
            raise HTTPException(status_code=502, detail=f"accounts endpoint unreachable: {exc}")
    if ar.status_code >= 400:
        raise HTTPException(status_code=ar.status_code, detail=f"cTrader account list failed: {ar.text}")
    accounts_payload = ar.json() or {}
    accounts = accounts_payload.get("data") or accounts_payload.get("accounts") or []
    if not accounts:
        # Surface the raw payload so the SPA can show "we got a token but no
        # accounts came back" instead of a silent success.
        return {"ok": False, "stored": 0, "raw": accounts_payload}

    # 3) Persist one row per account (encrypted at rest)
    for account in accounts:
        _upsert_connection(email=user["email"], account=account, tokens=tokens)

    return {
        "ok": True,
        "stored": len(accounts),
        "connections": _list_connections(user["email"]),
    }


@router.get("/connections")
def list_connections(user=Depends(get_current_user)):
    return {"connections": _list_connections(user["email"])}


@router.delete("/connections/{ctid}")
def disconnect(ctid: int, user=Depends(get_current_user)):
    """Soft-revoke (sets revoked_at). cTrader does not expose a programmatic
    token revoke endpoint, so we simply stop honouring the row."""
    ok = _revoke(user["email"], ctid)
    if not ok:
        raise HTTPException(status_code=404, detail="connection not found")
    return {"ok": True, "revoked_ctid": ctid}
