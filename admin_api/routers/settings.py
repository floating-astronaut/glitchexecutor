import os
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from typing import Optional

from auth import get_current_user, hash_password
from db import get_pg, log_audit

router = APIRouter()

# What admin_api actually reads from the environment in 2026.
# Refreshed 2026-05-18 — the previous list still referenced
# TELEGRAM_WEBHOOK_SECRET (gone from the codebase) and was missing
# the cTrader OAuth, payment-server, trade-admin, and Redis vars
# that admin_api genuinely depends on today. Grouped by purpose; the
# admin dashboard renders the groups verbatim. Presence only — values
# are never returned over the wire.
ENV_VARS_TO_CHECK = [
    # Auth + bootstrap
    "ADMIN_EMAIL",
    "ADMIN_PASSWORD",
    "ADMIN_JWT_SECRET",
    # Databases (admin_api PG16 + read-only views into product DBs)
    "DATABASE_URL",
    "ML_DATABASE_URL",
    "SA_DATABASE_URL",
    "REDIS_HOST",
    "REDIS_PORT",
    # Upstream proxies (admin_api forwards to these on behalf of the SPA)
    "PAYMENT_SERVICE_URL",
    "GROW_FULFILL_SECRET",
    "TRADE_API_URL",
    "TRADE_ADMIN_API_SECRET",
    # OAuth + customer-facing broker integrations
    "CTRADER_PUBLIC_CLIENT_ID",
    "CTRADER_PUBLIC_CLIENT_SECRET",
    "CTRADER_OAUTH_SCOPE",
    "IB_HOST",
    "IB_PORT",
    # Webhook secret (incoming trade-event POSTs from bots)
    "TRADE_WEBHOOK_SECRET",
    # SSO
    "SSO_TIMEOUT_SECONDS",
]


class CreateUserRequest(BaseModel):
    email: str
    password: str
    role: str = "admin"


class UpdateUserRequest(BaseModel):
    role: Optional[str] = None
    is_active: Optional[bool] = None


@router.get("/users")
def list_users(current_user: dict = Depends(get_current_user)):
    conn = get_pg()
    cur = conn.cursor()
    cur.execute(
        "SELECT id, email, role, is_active, created_at, last_login FROM admin_users ORDER BY created_at"
    )
    rows = [dict(r) for r in cur.fetchall()]
    cur.close()
    conn.close()
    return rows


@router.post("/users")
def create_user(
    body: CreateUserRequest,
    request: Request,
    current_user: dict = Depends(get_current_user)
):
    conn = get_pg()
    cur = conn.cursor()
    try:
        cur.execute(
            "INSERT INTO admin_users (email, password_hash, role) VALUES (%s, %s, %s) RETURNING id",
            (body.email, hash_password(body.password), body.role)
        )
        new_id = cur.fetchone()["id"]
        conn.commit()
    except Exception as e:
        conn.rollback()
        raise HTTPException(status_code=400, detail=str(e))
    finally:
        cur.close()
        conn.close()

    log_audit(
        current_user["email"], "create_admin_user",
        "admin_user", str(new_id),
        {"email": body.email, "role": body.role},
        request.client.host if request.client else None
    )
    return {"success": True, "id": new_id, "email": body.email}


@router.put("/users/{user_id}")
def update_user(
    user_id: int,
    body: UpdateUserRequest,
    request: Request,
    current_user: dict = Depends(get_current_user)
):
    conn = get_pg()
    cur = conn.cursor()
    updates = []
    params = []
    if body.role is not None:
        updates.append("role=%s")
        params.append(body.role)
    if body.is_active is not None:
        updates.append("is_active=%s")
        params.append(body.is_active)

    if not updates:
        raise HTTPException(status_code=400, detail="Nothing to update")

    params.append(user_id)
    cur.execute(f"UPDATE admin_users SET {', '.join(updates)} WHERE id=%s", params)
    conn.commit()
    cur.close()
    conn.close()

    log_audit(
        current_user["email"], "update_admin_user",
        "admin_user", str(user_id),
        body.dict(exclude_none=True),
        request.client.host if request.client else None
    )
    return {"success": True, "id": user_id}


@router.get("/audit")
def audit(
    page: int = 1,
    limit: int = 50,
    date_from: str = "",
    date_to: str = "",
    current_user: dict = Depends(get_current_user),
):
    conn = get_pg()
    cur = conn.cursor()

    where, params = ["1=1"], []
    if date_from:
        where.append("a.created_at >= %s::timestamptz")
        params.append(date_from)
    if date_to:
        where.append("a.created_at < (%s::date + INTERVAL '1 day')")
        params.append(date_to)
    where_sql = " AND ".join(where)

    cur.execute(f"SELECT COUNT(*) AS cnt FROM audit_log a WHERE {where_sql}", params)
    total = cur.fetchone()["cnt"]

    offset = (page - 1) * limit
    cur.execute(f"""
        SELECT a.id, u.email AS admin_email, a.action, a.target_type, a.target_id,
               a.details, a.ip_address, a.created_at
        FROM audit_log a
        LEFT JOIN admin_users u ON u.id = a.admin_user_id
        WHERE {where_sql}
        ORDER BY a.created_at DESC
        LIMIT %s OFFSET %s
    """, [*params, limit, offset])
    rows = [dict(r) for r in cur.fetchall()]
    cur.close()
    conn.close()

    return {"total": total, "page": page, "limit": limit, "entries": rows}


@router.get("/env-status")
def env_status(current_user: dict = Depends(get_current_user)):
    return {var: bool(os.environ.get(var)) for var in ENV_VARS_TO_CHECK}
