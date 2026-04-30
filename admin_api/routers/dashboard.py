"""
Admin home dashboard — KPIs, alerts, recent activity.

After the MT5 → Ouroboros (cTrader) migration, this router reads from:
- glitchexecutor DB (customers, billing, query_log)  via get_pg()
- glitch_ml DB     (ml_signals, ml_trades, ml_oracle_decisions) via get_ml_pg()
"""
from datetime import datetime, timezone, date
from fastapi import APIRouter, Depends

from auth import get_current_user
from db import get_pg, get_ml_pg

router = APIRouter()

TIER_PRICES = {"starter": 49, "pro": 149, "elite": 349}

# Trade engine considered healthy if any signal arrived in the last N seconds
TRADE_ENGINE_FRESH_SEC = 120


def _trade_engine_status() -> dict:
    """Health of the Ouroboros stack derived from ml_signals freshness."""
    try:
        conn = get_ml_pg()
        cur = conn.cursor()
        cur.execute(
            "SELECT EXTRACT(EPOCH FROM NOW() - MAX(created_at)) AS age_sec FROM ml_signals"
        )
        row = cur.fetchone()
        cur.close()
        conn.close()
        age = row["age_sec"]
        if age is None:
            return {"status": "no_data", "age_sec": None}
        age = int(age)
        if age <= TRADE_ENGINE_FRESH_SEC:
            return {"status": "healthy", "age_sec": age}
        if age <= TRADE_ENGINE_FRESH_SEC * 5:
            return {"status": "stale", "age_sec": age}
        return {"status": "offline", "age_sec": age}
    except Exception as e:
        return {"status": "unreachable", "age_sec": None, "error": str(e)}


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
        conn.rollback()

    today = date.today().isoformat()
    try:
        cur.execute(
            "SELECT COALESCE(SUM(llm_cost_usd), 0) AS cost FROM query_log WHERE DATE(created_at)=%s",
            (today,)
        )
        query_cost_today = float(cur.fetchone()["cost"])
    except Exception:
        query_cost_today = 0.0

    cur.close()
    conn.close()

    # Ouroboros KPIs from glitch_ml
    trade_kpis = {
        "trades_open": 0,
        "trades_today": 0,
        "signals_today": 0,
        "account_equity": 0.0,
    }
    try:
        ml = get_ml_pg()
        cml = ml.cursor()
        cml.execute("SELECT COUNT(*) AS c FROM ml_trades WHERE closed_at IS NULL")
        trade_kpis["trades_open"] = cml.fetchone()["c"]
        cml.execute(
            "SELECT COUNT(*) AS c FROM ml_trades WHERE opened_at::date = CURRENT_DATE"
        )
        trade_kpis["trades_today"] = cml.fetchone()["c"]
        cml.execute(
            "SELECT COUNT(*) AS c FROM ml_signals WHERE created_at::date = CURRENT_DATE"
        )
        trade_kpis["signals_today"] = cml.fetchone()["c"]
        cml.execute(
            """SELECT account_equity FROM ml_trades
               WHERE account_equity IS NOT NULL
               ORDER BY opened_at DESC LIMIT 1"""
        )
        row = cml.fetchone()
        if row:
            trade_kpis["account_equity"] = float(row["account_equity"])
        cml.close()
        ml.close()
    except Exception:
        pass

    return {
        "total_customers": total_customers,
        "by_tier": by_tier,
        "active_customers": active_customers,
        "mrr_usd": mrr,
        "arr_usd": mrr * 12,
        "email_signups": email_signups,
        "query_cost_today_usd": round(query_cost_today, 4),
        "trade_engine": _trade_engine_status(),
        **trade_kpis,
    }


@router.get("/alerts")
def alerts(current_user: dict = Depends(get_current_user)):
    result = []
    now = datetime.now(timezone.utc).isoformat()

    # Suspended customers
    try:
        conn = get_pg()
        cur = conn.cursor()
        cur.execute("SELECT COUNT(*) AS cnt FROM customers WHERE status='suspended'")
        suspended = cur.fetchone()["cnt"]
        if suspended > 0:
            result.append({
                "type": "suspended_customers",
                "severity": "warning",
                "message": f"{suspended} customer(s) currently suspended",
                "created_at": now,
            })
        cur.close()
        conn.close()
    except Exception:
        pass

    # Trade engine health
    te = _trade_engine_status()
    if te["status"] == "stale":
        result.append({
            "type": "trade_engine_stale",
            "severity": "warning",
            "message": f"Ouroboros has not produced a signal in {te['age_sec']}s",
            "created_at": now,
        })
    elif te["status"] in ("offline", "unreachable"):
        result.append({
            "type": "trade_engine_offline",
            "severity": "critical",
            "message": "Ouroboros trade engine is offline",
            "created_at": now,
        })

    return result


@router.get("/activity")
def activity(current_user: dict = Depends(get_current_user)):
    """Recent platform activity — Ouroboros trades + customer queries."""
    items: list[dict] = []

    # Trades opened/closed (Ouroboros)
    try:
        ml = get_ml_pg()
        cml = ml.cursor()
        cml.execute("""
            SELECT bot_name, symbol, side, opened_at, closed_at, exit_reason, pnl
            FROM ml_trades
            ORDER BY GREATEST(opened_at, COALESCE(closed_at, opened_at)) DESC
            LIMIT 25
        """)
        for r in cml.fetchall():
            opened, closed = r["opened_at"], r["closed_at"]
            # Emit one entry for the most recent event on this trade
            if closed and (not opened or closed > opened):
                items.append({
                    "type": "trade_close",
                    "customer": r["bot_name"],
                    "symbol": r["symbol"],
                    "action": f"close {r['side']} ({r['exit_reason'] or '—'}) pnl={r['pnl']:.2f}" if r["pnl"] is not None else f"close {r['side']}",
                    "created_at": closed.isoformat(),
                })
            else:
                items.append({
                    "type": "trade_open",
                    "customer": r["bot_name"],
                    "symbol": r["symbol"],
                    "action": f"open {r['side']}",
                    "created_at": opened.isoformat() if opened else None,
                })
        cml.close()
        ml.close()
    except Exception:
        pass

    # Customer queries
    try:
        conn = get_pg()
        cur = conn.cursor()
        cur.execute("""
            SELECT q.created_at, c.username, q.symbol, q.action
            FROM query_log q
            LEFT JOIN customers c ON c.telegram_id = q.telegram_id
            ORDER BY q.created_at DESC
            LIMIT 15
        """)
        for r in cur.fetchall():
            items.append({
                "type": "query",
                "customer": r.get("username") or "unknown",
                "symbol": r.get("symbol"),
                "action": r.get("action") or "query",
                "created_at": r["created_at"].isoformat() if r["created_at"] else None,
            })
        cur.close()
        conn.close()
    except Exception:
        pass

    items.sort(key=lambda x: x.get("created_at") or "", reverse=True)
    return items[:30]
