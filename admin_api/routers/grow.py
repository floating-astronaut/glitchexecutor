"""
Grow vertical API.

Currently surfaces the live Glitch Budz business via the
sales_agent schema in the host postgres glitch_sales_agent DB.

All endpoints are READ-ONLY (admin_api uses the glitch_sa_ro role).
HITL approve/reject actions will be added later as a separate
write-capable router (or via a small POST shim against the discord
bot's existing approval surface).
"""
from typing import Optional

from fastapi import APIRouter, Depends, Query

from auth import get_current_user
from db import get_sa_pg

router = APIRouter()


def _apply_date_range(where: list, params: list, column: str,
                      date_from: Optional[str], date_to: Optional[str]):
    if date_from:
        where.append(f"{column} >= %s::timestamptz"); params.append(date_from)
    if date_to:
        where.append(f"{column} < (%s::date + INTERVAL '1 day')"); params.append(date_to)


# ── Glitch Budz overview ─────────────────────────────────────────────────────

@router.get("/budz/stats")
def budz_stats(user=Depends(get_current_user)):
    """Top-line KPIs for the Budz overview page."""
    conn = get_sa_pg()
    cur = conn.cursor()

    cur.execute("SELECT COUNT(*) AS c FROM leads")
    leads_total = cur.fetchone()["c"]

    cur.execute("SELECT status, COUNT(*) AS c FROM leads GROUP BY status")
    by_status = {r["status"]: r["c"] for r in cur.fetchall()}

    cur.execute("""
        SELECT approval_state, COUNT(*) AS c
        FROM email_drafts
        GROUP BY approval_state
    """)
    drafts_by_state = {r["approval_state"]: r["c"] for r in cur.fetchall()}

    cur.execute("""
        SELECT COUNT(*) AS sends_total,
               COUNT(*) FILTER (WHERE opened_first_at IS NOT NULL) AS opens,
               COUNT(*) FILTER (WHERE replied_at IS NOT NULL) AS replies,
               COUNT(*) FILTER (WHERE bounced) AS bounces,
               COUNT(*) FILTER (WHERE unsubscribed) AS unsubs
        FROM email_sends
    """)
    s = cur.fetchone()

    cur.execute("SELECT COUNT(*) AS c FROM email_drafts WHERE approval_state='pending'")
    pending = cur.fetchone()["c"]

    cur.execute(
        "SELECT COUNT(*) AS c FROM email_drafts WHERE created_at > NOW() - INTERVAL '24 hours'"
    )
    drafts_24h = cur.fetchone()["c"]

    cur.execute(
        "SELECT COUNT(*) AS c FROM email_sends WHERE sent_at > NOW() - INTERVAL '24 hours'"
    )
    sends_24h = cur.fetchone()["c"]

    cur.close()
    conn.close()

    open_rate = (s["opens"] / s["sends_total"] * 100) if s["sends_total"] else None
    reply_rate = (s["replies"] / s["sends_total"] * 100) if s["sends_total"] else None

    return {
        "leads_total": leads_total,
        "leads_by_status": by_status,
        "drafts_by_state": drafts_by_state,
        "drafts_24h": drafts_24h,
        "drafts_pending": pending,
        "sends_total": s["sends_total"],
        "sends_24h": sends_24h,
        "opens": s["opens"],
        "replies": s["replies"],
        "bounces": s["bounces"],
        "unsubs": s["unsubs"],
        "open_rate_pct": round(open_rate, 1) if open_rate is not None else None,
        "reply_rate_pct": round(reply_rate, 1) if reply_rate is not None else None,
    }


# ── Leads ────────────────────────────────────────────────────────────────────

@router.get("/budz/leads")
def budz_leads(
    user=Depends(get_current_user),
    status: Optional[str] = None,
    search: Optional[str] = None,
    date_from: Optional[str] = Query(None, regex=r"^\d{4}-\d{2}-\d{2}$"),
    date_to: Optional[str] = Query(None, regex=r"^\d{4}-\d{2}-\d{2}$"),
    limit: int = Query(20, ge=1, le=500),
    page: int = Query(1, ge=1),
):
    where, params = ["1=1"], []
    if status:
        where.append("status = %s"); params.append(status)
    if search:
        where.append("(business_name ILIKE %s OR contact_email ILIKE %s OR city ILIKE %s)")
        like = f"%{search}%"
        params.extend([like, like, like])
    _apply_date_range(where, params, "created_at", date_from, date_to)
    where_sql = " AND ".join(where)
    offset = (page - 1) * limit

    conn = get_sa_pg()
    cur = conn.cursor()
    cur.execute(f"SELECT COUNT(*) AS c FROM leads WHERE {where_sql}", params)
    total = cur.fetchone()["c"]
    cur.execute(
        f"""SELECT id, created_at, source, business_name, city, province,
                   contact_email, contact_email_verified, current_site_status,
                   score, status, paused_reason, website_url, phone
            FROM leads
            WHERE {where_sql}
            ORDER BY created_at DESC
            LIMIT %s OFFSET %s""",
        [*params, limit, offset],
    )
    rows = [dict(r) for r in cur.fetchall()]
    cur.close()
    conn.close()
    for r in rows:
        if r.get("created_at"): r["created_at"] = r["created_at"].isoformat()
        if r.get("id"): r["id"] = str(r["id"])
    return {"total": total, "page": page, "limit": limit, "rows": rows}


# ── Drafts (HITL inbox lives here filtered by approval_state='pending') ──────

@router.get("/budz/drafts")
def budz_drafts(
    user=Depends(get_current_user),
    approval_state: Optional[str] = Query(None, regex="^(pending|approved|rejected|edited|superseded)$"),
    date_from: Optional[str] = Query(None, regex=r"^\d{4}-\d{2}-\d{2}$"),
    date_to: Optional[str] = Query(None, regex=r"^\d{4}-\d{2}-\d{2}$"),
    limit: int = Query(20, ge=1, le=500),
    page: int = Query(1, ge=1),
):
    where, params = ["1=1"], []
    if approval_state:
        where.append("d.approval_state = %s"); params.append(approval_state)
    _apply_date_range(where, params, "d.created_at", date_from, date_to)
    where_sql = " AND ".join(where)
    offset = (page - 1) * limit

    conn = get_sa_pg()
    cur = conn.cursor()
    cur.execute(f"SELECT COUNT(*) AS c FROM email_drafts d WHERE {where_sql}", params)
    total = cur.fetchone()["c"]
    cur.execute(
        f"""SELECT d.id, d.created_at, d.recipe_key, d.subject_variant,
                   d.subject, d.body, d.model, d.model_cost_usd,
                   d.approval_state, d.approved_at, d.approved_by_text,
                   d.discord_message_id,
                   l.business_name, l.contact_email, l.city
            FROM email_drafts d
            LEFT JOIN leads l ON l.id = d.lead_id
            WHERE {where_sql}
            ORDER BY d.created_at DESC
            LIMIT %s OFFSET %s""",
        [*params, limit, offset],
    )
    rows = [dict(r) for r in cur.fetchall()]
    cur.close()
    conn.close()
    for r in rows:
        for k in ("created_at", "approved_at"):
            if r.get(k): r[k] = r[k].isoformat()
        if r.get("id"): r["id"] = str(r["id"])
        if r.get("model_cost_usd"): r["model_cost_usd"] = float(r["model_cost_usd"])
    return {"total": total, "page": page, "limit": limit, "rows": rows}


# ── Sends (with open/reply tracking) ─────────────────────────────────────────

@router.get("/budz/sends")
def budz_sends(
    user=Depends(get_current_user),
    date_from: Optional[str] = Query(None, regex=r"^\d{4}-\d{2}-\d{2}$"),
    date_to: Optional[str] = Query(None, regex=r"^\d{4}-\d{2}-\d{2}$"),
    limit: int = Query(20, ge=1, le=500),
    page: int = Query(1, ge=1),
):
    where, params = ["1=1"], []
    _apply_date_range(where, params, "s.sent_at", date_from, date_to)
    where_sql = " AND ".join(where)
    offset = (page - 1) * limit

    conn = get_sa_pg()
    cur = conn.cursor()
    cur.execute(f"SELECT COUNT(*) AS c FROM email_sends s WHERE {where_sql}", params)
    total = cur.fetchone()["c"]
    cur.execute(
        f"""SELECT s.id, s.sent_at, s.from_email, s.to_email, s.subject,
                   s.opened_first_at, s.opened_count, s.replied_at,
                   s.reply_thread_count, s.bounced, s.unsubscribed,
                   s.follow_up_seq, l.business_name
            FROM email_sends s
            LEFT JOIN leads l ON l.id = s.lead_id
            WHERE {where_sql}
            ORDER BY s.sent_at DESC
            LIMIT %s OFFSET %s""",
        [*params, limit, offset],
    )
    rows = [dict(r) for r in cur.fetchall()]
    cur.close()
    conn.close()
    for r in rows:
        for k in ("sent_at", "opened_first_at", "replied_at"):
            if r.get(k): r[k] = r[k].isoformat()
        if r.get("id"): r["id"] = str(r["id"])
    return {"total": total, "page": page, "limit": limit, "rows": rows}


# ── Funnel snapshot ──────────────────────────────────────────────────────────

@router.get("/budz/funnel")
def budz_funnel(user=Depends(get_current_user)):
    conn = get_sa_pg()
    cur = conn.cursor()
    try:
        cur.execute("SELECT * FROM funnel_v ORDER BY 1")
        rows = [dict(r) for r in cur.fetchall()]
    except Exception:
        rows = []
    cur.close()
    conn.close()
    return rows
