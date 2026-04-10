import os
from datetime import datetime, timezone, date
from fastapi import APIRouter, Depends
import httpx

from auth import get_current_user
from db import get_pg

router = APIRouter()

TIER_PRICES = {"starter": 49, "pro": 149, "elite": 349}
DASHBOARD_URL = os.environ.get("DASHBOARD_URL", "http://172.17.0.1:5000")


def _dashboard_get(path: str, timeout: float = 5.0):
    try:
        r = httpx.get(f"{DASHBOARD_URL}{path}", timeout=timeout)
        r.raise_for_status()
        return r.json()
    except Exception as e:
        return {"error": str(e)}


@router.get("/kpis")
def kpis(current_user: dict = Depends(get_current_user)):
    conn = get_pg()
    cur = conn.cursor()

    cur.execute("SELECT COUNT(*) AS total FROM customers")
    total_customers = cur.fetchone()["total"]

    cur.execute("SELECT tier, COUNT(*) AS cnt FROM customers GROUP BY tier")
    by_tier = {row["tier"]: row["cnt"] for row in cur.fetchall()}

    cur.execute("SELECT COUNT(*) AS cnt FROM customers WHERE status='active'")
    active_customers = cur.fetchone()["cnt"]

    mrr = sum(TIER_PRICES.get(tier, 0) * count for tier, count in by_tier.items()
              if tier in TIER_PRICES)

    email_signups = 0
    try:
        cur.execute("SELECT COUNT(*) AS cnt FROM email_signups")
        email_signups = cur.fetchone()["cnt"]
    except Exception:
        conn.rollback()  # clear the aborted transaction state

    today = date.today().isoformat()
    try:
        cur.execute(
            "SELECT COALESCE(SUM(llm_cost_usd), 0) AS cost FROM query_log WHERE DATE(created_at)=%s",
            (today,)
        )
        query_cost_today = float(cur.fetchone()["cost"])
    except Exception:
        query_cost_today = 0.0

    # Auto-execute trades + strong-signal notify metrics
    auto_execute_trades_today = 0
    auto_execute_users = 0
    strong_signal_notify_users = 0
    try:
        cur.execute(
            "SELECT COUNT(*) AS cnt FROM trades WHERE DATE(created_at) = CURRENT_DATE"
        )
        auto_execute_trades_today = cur.fetchone()["cnt"]
        cur.execute(
            "SELECT COUNT(*) AS cnt FROM user_preferences WHERE auto_execute_enabled = TRUE"
        )
        auto_execute_users = cur.fetchone()["cnt"]
        cur.execute("""
            SELECT COUNT(*) AS cnt FROM user_preferences
            WHERE COALESCE(strong_signal_notify, TRUE) = TRUE
              AND array_length(COALESCE(favorite_symbols, ARRAY[]::text[]), 1) > 0
        """)
        strong_signal_notify_users = cur.fetchone()["cnt"]
    except Exception:
        pass

    cur.close()
    conn.close()

    ensemble_status = "unknown"
    try:
        r = httpx.get("http://glitch-ensemble:8100/health", timeout=3.0)
        ensemble_status = "healthy" if r.status_code == 200 else "unhealthy"
    except Exception:
        ensemble_status = "unreachable"

    return {
        "total_customers": total_customers,
        "by_tier": by_tier,
        "active_customers": active_customers,
        "mrr_usd": mrr,
        "arr_usd": mrr * 12,
        "email_signups": email_signups,
        "ensemble_status": ensemble_status,
        "auto_execute_trades_today": auto_execute_trades_today,
        "auto_execute_users": auto_execute_users,
        "strong_signal_notify_users": strong_signal_notify_users,
        "query_cost_today_usd": round(query_cost_today, 4),
    }


@router.get("/alerts")
def alerts(current_user: dict = Depends(get_current_user)):
    result = []
    conn = get_pg()
    cur = conn.cursor()

    cur.execute("SELECT COUNT(*) AS cnt FROM customers WHERE status='suspended'")
    suspended = cur.fetchone()["cnt"]
    if suspended > 0:
        result.append({
            "type": "suspended_customers",
            "severity": "warning",
            "message": f"{suspended} customer(s) currently suspended",
            "created_at": datetime.now(timezone.utc).isoformat()
        })

    cur.close()
    conn.close()

    try:
        r = httpx.get("http://glitch-ensemble:8100/health", timeout=3.0)
        if r.status_code != 200:
            result.append({
                "type": "ensemble_unhealthy",
                "severity": "critical",
                "message": "Ensemble engine is returning non-200 status",
                "created_at": datetime.now(timezone.utc).isoformat()
            })
    except Exception:
        result.append({
            "type": "ensemble_unreachable",
            "severity": "critical",
            "message": "Ensemble engine is unreachable",
            "created_at": datetime.now(timezone.utc).isoformat()
        })

    return result


@router.get("/activity")
def activity(current_user: dict = Depends(get_current_user)):
    items = []
    conn = get_pg()
    cur = conn.cursor()

    try:
        cur.execute("""
            SELECT q.created_at, c.username, q.symbol, q.action, q.llm_cost_usd
            FROM query_log q
            LEFT JOIN customers c ON c.telegram_id = q.telegram_id
            ORDER BY q.created_at DESC
            LIMIT 25
        """)
        for row in cur.fetchall():
            items.append({
                "type": "query",
                "customer": row.get("username", "unknown"),
                "symbol": row.get("symbol"),
                "action": row.get("action", "query"),
                "created_at": row["created_at"].isoformat() if row["created_at"] else None,
            })
    except Exception:
        pass

    cur.close()
    conn.close()

    # Recent bot events from bot_events table
    try:
        conn3 = get_pg()
        cur3 = conn3.cursor()
        cur3.execute("""
            SELECT bot, event_type, symbol, direction, ticket, received_at
            FROM bot_events
            ORDER BY received_at DESC
            LIMIT 25
        """)
        for row in cur3.fetchall():
            direction = row.get("direction") or ""
            symbol = row.get("symbol") or "—"
            action = f"{row['event_type']} {direction}".strip() if direction else row["event_type"]
            items.append({
                "type": f"bot_{row['event_type']}",
                "customer": row["bot"],
                "symbol": symbol,
                "action": action,
                "created_at": row["received_at"].isoformat() if row["received_at"] else None,
            })
        cur3.close()
        conn3.close()
    except Exception:
        pass

    items.sort(key=lambda x: x.get("created_at") or "", reverse=True)
    return items[:50]
