"""
Trade vertical API — reads from the Ouroboros (glitch_ml) DB on host postgres.

All endpoints require JWT auth. Read-only against the ml_* tables written
by the glitch-ml-collector systemd service (cTrader demo).

Tables surfaced:
    ml_signals             — every model vote, every bar
    ml_trades              — actual demo trades (open + closed, with PnL)
    ml_oracle_decisions    — per-symbol BUY/SELL/HOLD decisions
    ml_oracle_weights      — per-bot weight + veto + freshness
    ml_oracle_blocks       — blocked proposals with reasons
    ml_oracle_risk_limits  — scope-based lot/trade caps
    ml_news_events         — relevant news headlines
    ml_collector_state     — collector internal state (per-key json)
    ml_bars                — OHLCV (for charts)
"""
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, Query, HTTPException

from auth import get_current_user
from db import get_ml_pg

router = APIRouter()


# Bot heartbeat thresholds (minutes) — derived from signal cadence per bot
BOT_THRESHOLDS: dict[str, int] = {
    "hydra":    2,    # tick / very fast
    "viper":    5,
    "mamba":    20,
    "taipan":   45,
    "cobra":    45,
    "anaconda": 240,  # H4 cadence
}
DEFAULT_THRESH = 30


def _bot_status(last_signal: datetime | None, bot: str) -> str:
    if not last_signal:
        return "offline"
    if last_signal.tzinfo is None:
        last_signal = last_signal.replace(tzinfo=timezone.utc)
    minutes_ago = (datetime.now(timezone.utc) - last_signal).total_seconds() / 60
    online = BOT_THRESHOLDS.get(bot, DEFAULT_THRESH)
    if minutes_ago < online:
        return "online"
    if minutes_ago < online * 3:
        return "warning"
    return "offline"


# ── Bots ─────────────────────────────────────────────────────────────────────

@router.get("/bots")
def list_bots(user=Depends(get_current_user)):
    """List the live Ouroboros bots with status derived from ml_signals activity."""
    conn = get_ml_pg()
    cur = conn.cursor()
    cur.execute("""
        SELECT bot_name,
               COUNT(*) AS signal_count,
               COUNT(*) FILTER (WHERE executed) AS executed_count,
               MAX(created_at) AS last_signal,
               COUNT(DISTINCT symbol) AS symbols
        FROM ml_signals
        WHERE created_at > NOW() - INTERVAL '7 days'
        GROUP BY bot_name
        ORDER BY last_signal DESC NULLS LAST
    """)
    rows = cur.fetchall()
    cur.close()
    conn.close()

    out = []
    for r in rows:
        last = r["last_signal"]
        out.append({
            "bot": r["bot_name"],
            "status": _bot_status(last, r["bot_name"]),
            "signal_count_7d": r["signal_count"],
            "executed_count_7d": r["executed_count"],
            "symbols": r["symbols"],
            "last_signal_at": last.isoformat() if last else None,
        })
    return out


# ── Signals ──────────────────────────────────────────────────────────────────

@router.get("/signals")
def list_signals(
    user=Depends(get_current_user),
    bot: Optional[str] = None,
    symbol: Optional[str] = None,
    vote: Optional[str] = Query(None, regex="^(BUY|SELL|HOLD)$"),
    executed: Optional[bool] = None,
    limit: int = Query(50, ge=1, le=500),
    page: int = Query(1, ge=1),
):
    """Paginated recent signals, filterable by bot/symbol/vote/executed."""
    where, params = ["1=1"], []
    if bot:
        where.append("bot_name = %s"); params.append(bot)
    if symbol:
        where.append("symbol = %s"); params.append(symbol)
    if vote:
        where.append("vote = %s"); params.append(vote)
    if executed is not None:
        where.append("executed = %s"); params.append(executed)
    where_sql = " AND ".join(where)
    offset = (page - 1) * limit

    conn = get_ml_pg()
    cur = conn.cursor()
    cur.execute(f"SELECT COUNT(*) AS c FROM ml_signals WHERE {where_sql}", params)
    total = cur.fetchone()["c"]
    cur.execute(
        f"""SELECT id, signal_id, created_at, bot_name, model_name, symbol,
                   timeframe, vote, confidence, reasoning, executed, trade_id,
                   bar_close
            FROM ml_signals
            WHERE {where_sql}
            ORDER BY created_at DESC
            LIMIT %s OFFSET %s""",
        [*params, limit, offset],
    )
    rows = [dict(r) for r in cur.fetchall()]
    cur.close()
    conn.close()
    for r in rows:
        if r.get("created_at"):
            r["created_at"] = r["created_at"].isoformat()
        if r.get("signal_id"):
            r["signal_id"] = str(r["signal_id"])
    return {"total": total, "page": page, "limit": limit, "rows": rows}


# ── Trades ───────────────────────────────────────────────────────────────────

@router.get("/trades")
def list_trades(
    user=Depends(get_current_user),
    status: Optional[str] = Query(None, regex="^(open|closed)$"),
    bot: Optional[str] = None,
    symbol: Optional[str] = None,
    limit: int = Query(50, ge=1, le=500),
    page: int = Query(1, ge=1),
):
    """Recent trades with pnl + outcome."""
    where, params = ["1=1"], []
    if status == "open":
        where.append("closed_at IS NULL")
    elif status == "closed":
        where.append("closed_at IS NOT NULL")
    if bot:
        where.append("bot_name = %s"); params.append(bot)
    if symbol:
        where.append("symbol = %s"); params.append(symbol)
    where_sql = " AND ".join(where)
    offset = (page - 1) * limit

    conn = get_ml_pg()
    cur = conn.cursor()
    cur.execute(f"SELECT COUNT(*) AS c FROM ml_trades WHERE {where_sql}", params)
    total = cur.fetchone()["c"]
    cur.execute(
        f"""SELECT id, trade_id, signal_id, bot_name, model_name, symbol,
                   timeframe, side, entry_price, sl_price, tp_price, volume_lots,
                   ticket, opened_at, exit_price, exit_reason, closed_at, pnl,
                   outcome, duration_minutes, signal_confidence
            FROM ml_trades
            WHERE {where_sql}
            ORDER BY opened_at DESC
            LIMIT %s OFFSET %s""",
        [*params, limit, offset],
    )
    rows = [dict(r) for r in cur.fetchall()]
    cur.close()
    conn.close()
    for r in rows:
        for key in ("opened_at", "closed_at"):
            if r.get(key):
                r[key] = r[key].isoformat()
        for key in ("trade_id", "signal_id"):
            if r.get(key):
                r[key] = str(r[key])
    return {"total": total, "page": page, "limit": limit, "rows": rows}


# ── Stats / KPIs ─────────────────────────────────────────────────────────────

@router.get("/stats")
def stats(days: int = Query(7, ge=1, le=90), user=Depends(get_current_user)):
    """Top-line KPIs for the Trade overview page."""
    conn = get_ml_pg()
    cur = conn.cursor()

    cur.execute(
        """SELECT COUNT(*) AS signals,
                  COUNT(*) FILTER (WHERE executed) AS executed,
                  AVG(confidence) AS avg_conf,
                  COUNT(DISTINCT symbol) AS symbols,
                  COUNT(DISTINCT bot_name) AS bots
           FROM ml_signals
           WHERE created_at > NOW() - (%s || ' days')::interval""",
        (days,),
    )
    sig = cur.fetchone()

    cur.execute(
        """SELECT COUNT(*) AS trades,
                  COUNT(*) FILTER (WHERE closed_at IS NULL) AS open_trades,
                  COUNT(*) FILTER (WHERE closed_at IS NOT NULL) AS closed_trades,
                  COUNT(*) FILTER (WHERE outcome = 'WIN') AS wins,
                  COUNT(*) FILTER (WHERE outcome = 'LOSS') AS losses,
                  COALESCE(SUM(pnl) FILTER (WHERE closed_at IS NOT NULL), 0) AS total_pnl,
                  AVG(duration_minutes) FILTER (WHERE closed_at IS NOT NULL) AS avg_duration_min
           FROM ml_trades
           WHERE opened_at > NOW() - (%s || ' days')::interval""",
        (days,),
    )
    tr = cur.fetchone()

    # Latest balance/equity snapshot from any open or recently closed trade
    cur.execute(
        """SELECT account_balance, account_equity, opened_at
           FROM ml_trades
           WHERE account_balance IS NOT NULL
           ORDER BY opened_at DESC LIMIT 1"""
    )
    bal = cur.fetchone() or {}

    cur.close()
    conn.close()

    closed = tr["closed_trades"] or 0
    win_rate = (tr["wins"] / closed * 100) if closed else None

    return {
        "days": days,
        "signals": sig["signals"],
        "executed": sig["executed"],
        "avg_confidence": float(sig["avg_conf"] or 0),
        "symbols": sig["symbols"],
        "bots": sig["bots"],
        "trades_total": tr["trades"],
        "trades_open": tr["open_trades"],
        "trades_closed": closed,
        "wins": tr["wins"],
        "losses": tr["losses"],
        "win_rate_pct": round(win_rate, 1) if win_rate is not None else None,
        "total_pnl": float(tr["total_pnl"] or 0),
        "avg_duration_min": float(tr["avg_duration_min"] or 0),
        "account_balance": float(bal.get("account_balance") or 0) if bal else 0,
        "account_equity": float(bal.get("account_equity") or 0) if bal else 0,
    }


# ── Per-symbol exposure ──────────────────────────────────────────────────────

@router.get("/symbols")
def symbol_breakdown(user=Depends(get_current_user)):
    """Open positions and recent activity grouped by symbol."""
    conn = get_ml_pg()
    cur = conn.cursor()
    cur.execute(
        """SELECT symbol,
                  COUNT(*) FILTER (WHERE closed_at IS NULL) AS open_positions,
                  SUM(volume_lots) FILTER (WHERE closed_at IS NULL) AS open_lots,
                  COUNT(*) FILTER (WHERE opened_at > NOW() - INTERVAL '24 hours') AS trades_24h,
                  COALESCE(SUM(pnl) FILTER (WHERE closed_at > NOW() - INTERVAL '24 hours'), 0) AS pnl_24h
           FROM ml_trades
           GROUP BY symbol
           HAVING COUNT(*) FILTER (WHERE closed_at IS NULL) > 0
               OR COUNT(*) FILTER (WHERE opened_at > NOW() - INTERVAL '24 hours') > 0
           ORDER BY open_positions DESC, trades_24h DESC"""
    )
    rows = [dict(r) for r in cur.fetchall()]
    cur.close()
    conn.close()
    for r in rows:
        r["open_lots"] = float(r["open_lots"] or 0)
        r["pnl_24h"] = float(r["pnl_24h"] or 0)
    return rows


# ── Oracle ───────────────────────────────────────────────────────────────────

@router.get("/oracle/decisions")
def oracle_decisions(
    user=Depends(get_current_user),
    symbol: Optional[str] = None,
    decision: Optional[str] = Query(None, regex="^(BUY|SELL|HOLD|ABSTAIN)$"),
    mode: Optional[str] = None,
    limit: int = Query(100, ge=1, le=500),
):
    where, params = ["1=1"], []
    if symbol:
        where.append("symbol = %s"); params.append(symbol)
    if decision:
        where.append("decision = %s"); params.append(decision)
    if mode:
        where.append("mode = %s"); params.append(mode)
    where_sql = " AND ".join(where)

    conn = get_ml_pg()
    cur = conn.cursor()
    cur.execute(
        f"""SELECT id, decision_id, created_at, symbol, decision,
                   decision_confidence, buy_score, sell_score, hold_score,
                   contributors, abstain_reason, mode, trade_id
            FROM ml_oracle_decisions
            WHERE {where_sql}
            ORDER BY created_at DESC
            LIMIT %s""",
        [*params, limit],
    )
    rows = [dict(r) for r in cur.fetchall()]
    cur.close()
    conn.close()
    for r in rows:
        if r.get("created_at"):
            r["created_at"] = r["created_at"].isoformat()
        for k in ("decision_id", "trade_id"):
            if r.get(k):
                r[k] = str(r[k])
    return rows


@router.get("/oracle/weights")
def oracle_weights(user=Depends(get_current_user)):
    conn = get_ml_pg()
    cur = conn.cursor()
    cur.execute(
        """SELECT bot_name, weight, can_veto, freshness_sec, updated_at, notes
           FROM ml_oracle_weights
           ORDER BY weight DESC, bot_name"""
    )
    rows = [dict(r) for r in cur.fetchall()]
    cur.close()
    conn.close()
    for r in rows:
        if r.get("updated_at"):
            r["updated_at"] = r["updated_at"].isoformat()
    return rows


@router.get("/oracle/blocks")
def oracle_blocks(
    user=Depends(get_current_user),
    bot: Optional[str] = None,
    symbol: Optional[str] = None,
    limit: int = Query(100, ge=1, le=500),
):
    where, params = ["1=1"], []
    if bot:
        where.append("bot_name = %s"); params.append(bot)
    if symbol:
        where.append("symbol = %s"); params.append(symbol)
    where_sql = " AND ".join(where)

    conn = get_ml_pg()
    cur = conn.cursor()
    cur.execute(
        f"""SELECT id, created_at, bot_name, symbol, side, proposed_lots,
                   block_reason, block_detail, signal_id
            FROM ml_oracle_blocks
            WHERE {where_sql}
            ORDER BY created_at DESC
            LIMIT %s""",
        [*params, limit],
    )
    rows = [dict(r) for r in cur.fetchall()]
    cur.close()
    conn.close()
    for r in rows:
        if r.get("created_at"):
            r["created_at"] = r["created_at"].isoformat()
        if r.get("signal_id"):
            r["signal_id"] = str(r["signal_id"])
    return rows


@router.get("/oracle/risk")
def oracle_risk_limits(user=Depends(get_current_user)):
    conn = get_ml_pg()
    cur = conn.cursor()
    cur.execute(
        """SELECT scope_type, scope_key, max_lots, max_trades, enabled, notes, updated_at
           FROM ml_oracle_risk_limits
           ORDER BY scope_type, scope_key"""
    )
    rows = [dict(r) for r in cur.fetchall()]
    cur.close()
    conn.close()
    for r in rows:
        if r.get("updated_at"):
            r["updated_at"] = r["updated_at"].isoformat()
    return rows


# ── News ─────────────────────────────────────────────────────────────────────

@router.get("/news")
def news(
    user=Depends(get_current_user),
    limit: int = Query(50, ge=1, le=200),
):
    conn = get_ml_pg()
    cur = conn.cursor()
    cur.execute(
        """SELECT id, created_at, article_id, title, description, link,
                  source, published_at, category, country, event_type, matched_rule_id
           FROM ml_news_events
           ORDER BY COALESCE(published_at, created_at) DESC
           LIMIT %s""",
        (limit,),
    )
    rows = [dict(r) for r in cur.fetchall()]
    cur.close()
    conn.close()
    for r in rows:
        for k in ("created_at", "published_at"):
            if r.get(k):
                r[k] = r[k].isoformat()
    return rows


# ── Collector state (read-only) ──────────────────────────────────────────────

@router.get("/state")
def collector_state(user=Depends(get_current_user)):
    """Internal collector state (key/value JSON)."""
    conn = get_ml_pg()
    cur = conn.cursor()
    cur.execute("SELECT key, value, updated_at FROM ml_collector_state ORDER BY key")
    rows = [dict(r) for r in cur.fetchall()]
    cur.close()
    conn.close()
    for r in rows:
        if r.get("updated_at"):
            r["updated_at"] = r["updated_at"].isoformat()
    return rows


# ── Bars (for charts) ────────────────────────────────────────────────────────

@router.get("/bars/{symbol}/{timeframe}")
def bars(
    symbol: str,
    timeframe: str,
    user=Depends(get_current_user),
    limit: int = Query(500, ge=10, le=5000),
):
    if timeframe not in {"M1", "M5", "M15", "M30", "H1", "H4", "D1"}:
        raise HTTPException(400, "invalid timeframe")
    conn = get_ml_pg()
    cur = conn.cursor()
    cur.execute(
        """SELECT bar_time, open, high, low, close, volume
           FROM ml_bars
           WHERE symbol = %s AND timeframe = %s
           ORDER BY bar_time DESC
           LIMIT %s""",
        (symbol, timeframe, limit),
    )
    rows = [dict(r) for r in cur.fetchall()]
    cur.close()
    conn.close()
    for r in rows:
        if r.get("bar_time"):
            r["bar_time"] = r["bar_time"].isoformat()
    rows.reverse()  # ascending order for chart consumption
    return rows
