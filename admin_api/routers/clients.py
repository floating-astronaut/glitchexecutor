from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from typing import Optional

from auth import get_current_user
from db import get_pg, log_audit

router = APIRouter()


class TierUpdate(BaseModel):
    tier: str


class StatusUpdate(BaseModel):
    status: str


VALID_TIERS = {"trial", "starter", "pro", "elite"}
VALID_STATUSES = {"active", "suspended", "cancelled", "pending"}


@router.get("")
def list_clients(
    page: int = 1,
    limit: int = 20,
    search: str = "",
    tier: str = "",
    status: str = "",
    current_user: dict = Depends(get_current_user)
):
    conn = get_pg()
    cur = conn.cursor()

    conditions = []
    params = []

    if search:
        conditions.append("(c.username ILIKE %s OR CAST(c.telegram_id AS TEXT) ILIKE %s)")
        like = f"%{search}%"
        params.extend([like, like])
    if tier:
        conditions.append("c.tier = %s")
        params.append(tier)
    if status:
        conditions.append("c.status = %s")
        params.append(status)

    where = ("WHERE " + " AND ".join(conditions)) if conditions else ""

    cur.execute(
        f"SELECT COUNT(*) AS cnt FROM customers c LEFT JOIN user_preferences up ON up.customer_id = c.id {where}",
        params
    )
    total = cur.fetchone()["cnt"]

    offset = (page - 1) * limit
    cur.execute(
        f"""SELECT c.id, c.telegram_id, c.username, c.tier, c.status,
                   c.created_at, c.queries_today,
                   COALESCE(array_length(COALESCE(up.favorite_symbols, ARRAY[]::text[]), 1), 0) AS favorites_count,
                   COALESCE(up.auto_execute_enabled, FALSE) AS auto_execute_enabled
            FROM customers c
            LEFT JOIN user_preferences up ON up.customer_id = c.id
            {where}
            ORDER BY c.created_at DESC LIMIT %s OFFSET %s""",
        params + [limit, offset]
    )
    rows = cur.fetchall()
    cur.close()
    conn.close()

    return {"total": total, "page": page, "limit": limit, "customers": [dict(r) for r in rows]}


@router.get("/{customer_id}")
def get_client(customer_id: int, current_user: dict = Depends(get_current_user)):
    conn = get_pg()
    cur = conn.cursor()

    cur.execute("SELECT * FROM customers WHERE id=%s", (customer_id,))
    customer = cur.fetchone()
    if not customer:
        raise HTTPException(status_code=404, detail="Customer not found")
    customer = dict(customer)

    # Last 20 query_log entries
    queries = []
    try:
        cur.execute("""
            SELECT created_at, symbol, action, llm_cost_usd
            FROM query_log WHERE telegram_id=%s
            ORDER BY created_at DESC LIMIT 20
        """, (customer.get("telegram_id"),))
        queries = [dict(r) for r in cur.fetchall()]
    except Exception:
        pass

    # Exchange keys (masked — never decrypt)
    keys = []
    try:
        cur.execute("""
            SELECT exchange, is_active, created_at
            FROM exchange_keys WHERE customer_id=%s
        """, (customer_id,))
        keys = [dict(r) for r in cur.fetchall()]
    except Exception:
        pass

    # User preferences (favorites + auto-execute)
    preferences = {}
    try:
        cur.execute("""
            SELECT favorite_symbols, auto_execute_enabled, strong_signal_notify
            FROM user_preferences WHERE customer_id=%s
        """, (customer_id,))
        row = cur.fetchone()
        if row:
            preferences = dict(row)
    except Exception:
        pass

    cur.close()
    conn.close()

    return {
        "customer": customer,
        "queries": queries,
        "exchange_keys": keys,
        "preferences": preferences,
    }


@router.put("/{customer_id}/tier")
def update_tier(
    customer_id: int,
    body: TierUpdate,
    request: Request,
    current_user: dict = Depends(get_current_user)
):
    if body.tier not in VALID_TIERS:
        raise HTTPException(status_code=400, detail=f"Invalid tier. Must be one of: {VALID_TIERS}")

    conn = get_pg()
    cur = conn.cursor()
    cur.execute("SELECT tier FROM customers WHERE id=%s", (customer_id,))
    row = cur.fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Customer not found")

    old_tier = row["tier"]
    cur.execute("UPDATE customers SET tier=%s WHERE id=%s", (body.tier, customer_id))
    conn.commit()
    cur.close()
    conn.close()

    log_audit(
        current_user["email"], "update_tier",
        "customer", str(customer_id),
        {"old_tier": old_tier, "new_tier": body.tier},
        request.client.host if request.client else None
    )

    return {"success": True, "customer_id": customer_id, "tier": body.tier}


@router.put("/{customer_id}/status")
def update_status(
    customer_id: int,
    body: StatusUpdate,
    request: Request,
    current_user: dict = Depends(get_current_user)
):
    if body.status not in VALID_STATUSES:
        raise HTTPException(status_code=400, detail=f"Invalid status. Must be one of: {VALID_STATUSES}")

    conn = get_pg()
    cur = conn.cursor()
    cur.execute("SELECT status FROM customers WHERE id=%s", (customer_id,))
    row = cur.fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Customer not found")

    old_status = row["status"]
    cur.execute("UPDATE customers SET status=%s WHERE id=%s", (body.status, customer_id))
    conn.commit()
    cur.close()
    conn.close()

    log_audit(
        current_user["email"], "update_status",
        "customer", str(customer_id),
        {"old_status": old_status, "new_status": body.status},
        request.client.host if request.client else None
    )

    return {"success": True, "customer_id": customer_id, "status": body.status}
