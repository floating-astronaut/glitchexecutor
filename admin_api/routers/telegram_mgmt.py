import os
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, Request, Query
from pydantic import BaseModel
import docker
import httpx

from auth import get_current_user
from db import get_pg, log_audit

router = APIRouter()

BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")


@router.get("/status")
def bot_status(current_user: dict = Depends(get_current_user)):
    try:
        client = docker.from_env()
        c = client.containers.get("glitch-telegram-bot")
        state = c.attrs.get("State", {})
        health = "none"
        if state.get("Health"):
            health = state["Health"].get("Status", "none")
        return {
            "running":    c.status == "running",
            "status":     c.status,
            "health":     health,
            "started_at": state.get("StartedAt"),
        }
    except Exception as e:
        return {"running": False, "status": "error", "health": "none", "error": str(e)}


@router.get("/stats")
def bot_stats(current_user: dict = Depends(get_current_user)):
    conn = get_pg()
    cur = conn.cursor()
    cur.execute("SELECT COUNT(*) AS cnt FROM customers")
    total = cur.fetchone()["cnt"]
    cur.execute("SELECT COUNT(*) AS cnt FROM customers WHERE queries_today > 0")
    active_today = cur.fetchone()["cnt"]
    cur.execute("SELECT COUNT(*) AS cnt FROM customers WHERE DATE(created_at) = CURRENT_DATE")
    new_today = cur.fetchone()["cnt"]
    cur.close()
    conn.close()
    return {"total_users": total, "active_today": active_today, "new_today": new_today}


@router.get("/logs")
def bot_logs(
    lines: int = Query(50, ge=10, le=500),
    current_user: dict = Depends(get_current_user),
):
    try:
        client = docker.from_env()
        c = client.containers.get("glitch-telegram-bot")
        raw = c.logs(tail=lines, timestamps=True)
        return {"content": raw.decode("utf-8", errors="replace")}
    except docker.errors.NotFound:
        return {"content": "", "error": "Container not found"}
    except Exception as e:
        return {"content": "", "error": str(e)}


@router.get("/users")
def list_tg_users(
    page:   int = 1,
    limit:  int = 25,
    search: str = "",
    current_user: dict = Depends(get_current_user),
):
    conn = get_pg()
    cur = conn.cursor()
    conditions, params = [], []
    if search:
        conditions.append("(username ILIKE %s OR CAST(telegram_id AS TEXT) ILIKE %s)")
        like = f"%{search}%"
        params.extend([like, like])
    where = ("WHERE " + " AND ".join(conditions)) if conditions else ""
    cur.execute(f"SELECT COUNT(*) AS cnt FROM customers {where}", params)
    total = cur.fetchone()["cnt"]
    offset = (page - 1) * limit
    cur.execute(
        f"""SELECT id, telegram_id, username, tier, status,
                   queries_today, created_at, trial_ends_at
            FROM customers {where}
            ORDER BY created_at DESC LIMIT %s OFFSET %s""",
        params + [limit, offset],
    )
    rows = [dict(r) for r in cur.fetchall()]
    cur.close()
    conn.close()
    return {"total": total, "page": page, "limit": limit, "customers": rows}


class BroadcastRequest(BaseModel):
    message: str
    tier: Optional[str] = None  # None = all active users


@router.post("/broadcast")
async def broadcast(
    body: BroadcastRequest,
    request: Request,
    current_user: dict = Depends(get_current_user),
):
    if not body.message.strip():
        raise HTTPException(status_code=400, detail="Message cannot be empty")
    if len(body.message) > 4096:
        raise HTTPException(status_code=400, detail="Message exceeds Telegram 4096-char limit")
    if not BOT_TOKEN:
        raise HTTPException(status_code=500, detail="TELEGRAM_BOT_TOKEN not configured")

    conn = get_pg()
    cur = conn.cursor()
    where = "WHERE status='active'"
    params: list = []
    if body.tier:
        where += " AND tier=%s"
        params.append(body.tier)
    cur.execute(f"SELECT telegram_id FROM customers {where}", params)
    ids = [r["telegram_id"] for r in cur.fetchall()]
    cur.close()
    conn.close()

    if len(ids) > 5000:
        raise HTTPException(status_code=400, detail=f"Too many recipients ({len(ids)}). Cap is 5000.")

    sent, failed = 0, 0
    async with httpx.AsyncClient(timeout=10) as client:
        for tid in ids:
            try:
                resp = await client.post(
                    f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage",
                    json={"chat_id": tid, "text": body.message, "parse_mode": "HTML"},
                )
                if resp.status_code == 200:
                    sent += 1
                else:
                    failed += 1
            except Exception:
                failed += 1

    log_audit(
        current_user["email"], "broadcast", "telegram", "all",
        {"tier": body.tier, "sent": sent, "failed": failed},
        request.client.host if request.client else None,
    )
    return {"sent": sent, "failed": failed, "total": len(ids)}


@router.get("/broadcast/preview")
def broadcast_preview(
    tier: Optional[str] = Query(None),
    current_user: dict = Depends(get_current_user),
):
    """Returns recipient count for a broadcast without sending."""
    conn = get_pg()
    cur = conn.cursor()
    where = "WHERE status='active'"
    params: list = []
    if tier:
        where += " AND tier=%s"
        params.append(tier)
    cur.execute(f"SELECT COUNT(*) AS cnt FROM customers {where}", params)
    count = cur.fetchone()["cnt"]
    cur.close()
    conn.close()
    return {"count": count, "tier": tier}


@router.post("/users/{customer_id}/reset-queries")
def reset_queries(
    customer_id: int,
    request: Request,
    current_user: dict = Depends(get_current_user),
):
    conn = get_pg()
    cur = conn.cursor()
    cur.execute(
        "UPDATE customers SET queries_today=0 WHERE id=%s RETURNING id",
        (customer_id,),
    )
    if not cur.fetchone():
        conn.close()
        raise HTTPException(status_code=404, detail="Customer not found")
    conn.commit()
    cur.close()
    conn.close()
    log_audit(
        current_user["email"], "reset_queries", "customer", str(customer_id), {},
        request.client.host if request.client else None,
    )
    return {"success": True}


class DMRequest(BaseModel):
    message: str


@router.post("/users/{customer_id}/send-dm")
async def send_dm(
    customer_id: int,
    body: DMRequest,
    request: Request,
    current_user: dict = Depends(get_current_user),
):
    if not body.message.strip():
        raise HTTPException(status_code=400, detail="Message cannot be empty")
    if len(body.message) > 4096:
        raise HTTPException(status_code=400, detail="Message too long")
    if not BOT_TOKEN:
        raise HTTPException(status_code=500, detail="TELEGRAM_BOT_TOKEN not configured")

    conn = get_pg()
    cur = conn.cursor()
    cur.execute("SELECT telegram_id FROM customers WHERE id=%s", (customer_id,))
    row = cur.fetchone()
    cur.close()
    conn.close()
    if not row:
        raise HTTPException(status_code=404, detail="Customer not found")

    async with httpx.AsyncClient(timeout=10) as client:
        resp = await client.post(
            f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage",
            json={"chat_id": row["telegram_id"], "text": body.message, "parse_mode": "HTML"},
        )

    log_audit(
        current_user["email"], "send_dm", "customer", str(customer_id),
        {"preview": body.message[:80]},
        request.client.host if request.client else None,
    )
    return {"success": resp.status_code == 200, "tg_status": resp.status_code}


class SuspendRequest(BaseModel):
    suspend: bool


@router.post("/users/{customer_id}/suspend")
def suspend_user(
    customer_id: int,
    body: SuspendRequest,
    request: Request,
    current_user: dict = Depends(get_current_user),
):
    new_status = "suspended" if body.suspend else "active"
    conn = get_pg()
    cur = conn.cursor()
    cur.execute(
        "UPDATE customers SET status=%s WHERE id=%s RETURNING id",
        (new_status, customer_id),
    )
    if not cur.fetchone():
        conn.close()
        raise HTTPException(status_code=404, detail="Customer not found")
    conn.commit()
    cur.close()
    conn.close()
    action = "suspend_user" if body.suspend else "unsuspend_user"
    log_audit(
        current_user["email"], action, "customer", str(customer_id),
        {"new_status": new_status},
        request.client.host if request.client else None,
    )
    return {"success": True, "status": new_status}
