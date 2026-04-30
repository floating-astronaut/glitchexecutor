from typing import Optional, List
from fastapi import APIRouter, Depends, HTTPException, Request, Query
from pydantic import BaseModel

from auth import get_current_user
from db import get_pg, log_audit

router = APIRouter()

VALID_TIERS    = {"trial", "starter", "pro", "elite"}
VALID_STATUSES = {"active", "suspended", "cancelled", "pending"}


@router.get("/customers")
def list_customers(
    page:   int = 1,
    limit:  int = 25,
    search: str = "",
    tier:   str = "",
    status: str = "",
    date_from: str = "",
    date_to:   str = "",
    current_user: dict = Depends(get_current_user),
):
    conn = get_pg()
    cur = conn.cursor()
    conditions, params = [], []
    if search:
        conditions.append(
            "(username ILIKE %s OR CAST(telegram_id AS TEXT) ILIKE %s "
            "OR COALESCE(stripe_customer_id,'') ILIKE %s)"
        )
        like = f"%{search}%"
        params.extend([like, like, like])
    if tier:
        conditions.append("tier=%s")
        params.append(tier)
    if status:
        conditions.append("status=%s")
        params.append(status)
    if date_from:
        conditions.append("created_at >= %s::timestamptz")
        params.append(date_from)
    if date_to:
        conditions.append("created_at < (%s::date + INTERVAL '1 day')")
        params.append(date_to)
    where = ("WHERE " + " AND ".join(conditions)) if conditions else ""
    cur.execute(f"SELECT COUNT(*) AS cnt FROM customers {where}", params)
    total = cur.fetchone()["cnt"]
    offset = (page - 1) * limit
    cur.execute(
        f"""SELECT id, telegram_id, username, tier, status,
                   queries_today, created_at, trial_ends_at,
                   stripe_customer_id, stripe_subscription_id, referral_code
            FROM customers {where}
            ORDER BY created_at DESC LIMIT %s OFFSET %s""",
        params + [limit, offset],
    )
    rows = [dict(r) for r in cur.fetchall()]
    cur.close()
    conn.close()
    return {"total": total, "page": page, "limit": limit, "customers": rows}


class PrefsUpdate(BaseModel):
    favorite_symbols:     Optional[List[str]] = None
    auto_execute_enabled: Optional[bool]      = None
    strong_signal_notify: Optional[bool]      = None


@router.put("/customers/{customer_id}/preferences")
def update_prefs(
    customer_id: int,
    body: PrefsUpdate,
    request: Request,
    current_user: dict = Depends(get_current_user),
):
    updates, vals = [], []
    if body.favorite_symbols is not None:
        updates.append("favorite_symbols=%s")
        vals.append(body.favorite_symbols)
    if body.auto_execute_enabled is not None:
        updates.append("auto_execute_enabled=%s")
        vals.append(body.auto_execute_enabled)
    if body.strong_signal_notify is not None:
        updates.append("strong_signal_notify=%s")
        vals.append(body.strong_signal_notify)
    if not updates:
        raise HTTPException(status_code=400, detail="Nothing to update")

    col_names = [u.split("=")[0] for u in updates]
    conn = get_pg()
    cur = conn.cursor()
    cur.execute(
        f"""INSERT INTO user_preferences (customer_id, {', '.join(col_names)})
            VALUES (%s, {', '.join(['%s'] * len(vals))})
            ON CONFLICT (customer_id) DO UPDATE
            SET {', '.join(updates)}""",
        [customer_id] + vals + vals,
    )
    conn.commit()
    cur.close()
    conn.close()
    log_audit(
        current_user["email"], "update_prefs", "customer", str(customer_id),
        {k: v for k, v in body.dict().items() if v is not None},
        request.client.host if request.client else None,
    )
    return {"success": True}


class BulkTierRequest(BaseModel):
    ids:  List[int]
    tier: str


@router.post("/customers/bulk-tier")
def bulk_tier(
    body: BulkTierRequest,
    request: Request,
    current_user: dict = Depends(get_current_user),
):
    if body.tier not in VALID_TIERS:
        raise HTTPException(status_code=400, detail=f"Invalid tier. Options: {VALID_TIERS}")
    if not body.ids:
        raise HTTPException(status_code=400, detail="No IDs provided")
    if len(body.ids) > 500:
        raise HTTPException(status_code=400, detail="Max 500 IDs per bulk operation")
    conn = get_pg()
    cur = conn.cursor()
    cur.execute("UPDATE customers SET tier=%s WHERE id=ANY(%s)", (body.tier, body.ids))
    conn.commit()
    cur.close()
    conn.close()
    log_audit(
        current_user["email"], "bulk_change_tier", "customer", f"ids:{body.ids[:10]}...",
        {"tier": body.tier, "count": len(body.ids)},
        request.client.host if request.client else None,
    )
    return {"success": True, "updated": len(body.ids)}


class BulkSuspendRequest(BaseModel):
    ids: List[int]


@router.post("/customers/bulk-suspend")
def bulk_suspend(
    body: BulkSuspendRequest,
    request: Request,
    current_user: dict = Depends(get_current_user),
):
    if not body.ids:
        raise HTTPException(status_code=400, detail="No IDs provided")
    if len(body.ids) > 500:
        raise HTTPException(status_code=400, detail="Max 500 IDs per bulk operation")
    conn = get_pg()
    cur = conn.cursor()
    cur.execute("UPDATE customers SET status='suspended' WHERE id=ANY(%s)", (body.ids,))
    conn.commit()
    cur.close()
    conn.close()
    log_audit(
        current_user["email"], "bulk_suspend", "customer", f"ids:{body.ids[:10]}...",
        {"count": len(body.ids)},
        request.client.host if request.client else None,
    )
    return {"success": True, "suspended": len(body.ids)}
