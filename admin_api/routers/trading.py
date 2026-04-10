import os
import json
from datetime import datetime, timezone
from fastapi import APIRouter, Depends
import httpx
import redis

from auth import get_current_user
from db import get_pg

router = APIRouter()

DASHBOARD_URL = os.environ.get("DASHBOARD_URL", "http://172.17.0.1:5000")


def get_redis():
    return redis.Redis(
        host=os.environ.get("REDIS_HOST", "redis"),
        port=int(os.environ.get("REDIS_PORT", 6379)),
        decode_responses=True
    )


def _dashboard_get(path: str, timeout: float = 5.0):
    """GET from the Flask dashboard API."""
    try:
        r = httpx.get(f"{DASHBOARD_URL}{path}", timeout=timeout)
        r.raise_for_status()
        return r.json()
    except Exception as e:
        return {"error": str(e)}


@router.get("/bots")
def bots(current_user: dict = Depends(get_current_user)):
    health = _dashboard_get("/api/health")
    if "error" in health:
        return []

    result = []
    for profile_key in ["terminal_a", "terminal_b"]:
        h = health.get(profile_key, {})
        if not h:
            continue
        result.append({
            "profile": profile_key,
            "status": h.get("status", "unknown"),
            "minutes_ago": h.get("minutes_ago"),
            "iteration": h.get("iteration"),
            "account": h.get("account"),
            "timeframe": h.get("timeframe"),
            "last_heartbeat": h.get("last_heartbeat"),
        })

    return result


@router.get("/bots/{profile}")
def bot_detail(profile: str, current_user: dict = Depends(get_current_user)):
    health = _dashboard_get("/api/health")
    stats_data = _dashboard_get("/api/stats")
    all_trades = _dashboard_get("/api/trades")
    all_trails = _dashboard_get("/api/trail-updates")

    hb = {}
    if "error" not in health:
        hb = health.get(profile, {})

    stats = {}
    if "error" not in stats_data:
        stats = stats_data.get(profile, {})

    trades = []
    if isinstance(all_trades, list):
        trades = [t for t in all_trades if t.get("profile") == profile][:50]

    trails = []
    if isinstance(all_trails, list):
        trails = [t for t in all_trails if t.get("profile") == profile][:20]

    return {
        "heartbeat": hb,
        "stats": stats,
        "trades": trades,
        "trail_updates": trails,
    }


@router.get("/ensemble")
def ensemble(current_user: dict = Depends(get_current_user)):
    health = {}
    try:
        r = httpx.get("http://glitch-ensemble:8100/health", timeout=5.0)
        health = r.json()
    except Exception as e:
        health = {"status": "unreachable", "error": str(e)}

    signals = {}
    try:
        rc = get_redis()
        keys = rc.keys("ensemble:*")
        for key in keys:
            val = rc.get(key)
            if val:
                try:
                    signals[key] = json.loads(val)
                except Exception:
                    signals[key] = val
    except Exception:
        pass

    return {"health": health, "signals": signals}


@router.get("/trades")
def trades(page: int = 1, limit: int = 50, current_user: dict = Depends(get_current_user)):
    page = max(page, 1)
    limit = min(max(limit, 1), 100)
    conn = get_pg()
    cur = conn.cursor()
    try:
        cur.execute("SELECT COUNT(*) AS cnt FROM trades")
        total = cur.fetchone()["cnt"]

        offset = (page - 1) * limit
        cur.execute("""
            SELECT t.id, t.customer_id, c.username, t.symbol, t.direction,
                   t.entry_price, t.sl_price, t.tp_price, t.volume,
                   t.ensemble_vote, t.status, t.created_at
            FROM trades t
            LEFT JOIN customers c ON c.id = t.customer_id
            ORDER BY t.created_at DESC
            LIMIT %s OFFSET %s
        """, (limit, offset))
        trades_data = [dict(r) for r in cur.fetchall()]
        cur.close()
        conn.close()
        return {"total": total, "page": page, "limit": limit, "trades": trades_data}
    except Exception as e:
        try:
            cur.close()
            conn.close()
        except Exception:
            pass
        return {"error": str(e), "trades": [], "total": 0}


@router.get("/signals")
def signals(current_user: dict = Depends(get_current_user)):
    result = {}
    try:
        rc = get_redis()
        symbols = ["BTCUSD", "ETHUSD", "SOLUSD", "XRPUSD", "BNBUSD",
                   "XAUUSD", "EURUSD", "USOUSD"]
        for symbol in symbols:
            for key_template in [f"ensemble:{symbol}", f"signal:{symbol}", f"ensemble:{symbol.lower()}"]:
                val = rc.get(key_template)
                if val:
                    try:
                        result[symbol] = json.loads(val)
                    except Exception:
                        result[symbol] = {"raw": val}
                    break
    except Exception:
        pass
    return result
