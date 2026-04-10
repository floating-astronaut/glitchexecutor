"""
Bot data API — serves the Trading dashboard.
All endpoints require JWT auth.
"""
from datetime import datetime, timezone
from typing import Optional
from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel

from auth import get_current_user
from db import get_pg

router = APIRouter()

# Current trading bots shown in the status grid (hawk is legacy name for anaconda)
BOTS = ["viper3", "anaconda", "mamba", "cobra", "taipan"]

# Human-readable display names
BOT_DISPLAY: dict[str, str] = {
    "viper3":   "Viper",
    "anaconda": "Anaconda",
    "hawk":     "Anaconda",   # hawk = legacy name for anaconda
    "mamba":    "Mamba",
    "cobra":    "Cobra",
    "taipan":   "Taipan",
}

# Per-bot heartbeat thresholds (minutes)
# online_thresh  = max minutes since last heartbeat → "online"
# warning_thresh = online_thresh × 2               → "warning"
BOT_THRESHOLDS: dict[str, int] = {
    "viper3":   2,    # M5 bot — heartbeat every ~10 s
    "anaconda": 20,   # H4 bot — slower heartbeat cadence
    "hawk":     20,   # legacy name; same threshold as anaconda
    "mamba":    5,    # M15
    "cobra":    10,   # M30
    "taipan":   10,   # M30 Asian session
}


def _bot_status(bot: str, last_seen: datetime | None) -> str:
    if not last_seen:
        return "offline"
    if last_seen.tzinfo is None:
        last_seen = last_seen.replace(tzinfo=timezone.utc)
    minutes_ago = (datetime.now(timezone.utc) - last_seen).total_seconds() / 60
    online_thresh  = BOT_THRESHOLDS.get(bot, 15)
    warning_thresh = online_thresh * 2
    if minutes_ago < online_thresh:
        return "online"
    if minutes_ago < warning_thresh:
        return "warning"
    return "offline"


# ── GET /api/bots/heartbeats ───────────────────────────────────────────────────

@router.get("/heartbeats")
def heartbeats(current_user: dict = Depends(get_current_user)):
    """Return status for all trading bots (online / warning / offline)."""
    conn = get_pg()
    cur = conn.cursor()
    cur.execute("SELECT * FROM bot_heartbeats WHERE bot != 'oracle'")
    rows = {r["bot"]: dict(r) for r in cur.fetchall()}
    cur.close()
    conn.close()

    result = []
    for bot in BOTS:
        row = rows.get(bot, {})
        last_seen = row.get("last_seen")
        minutes_ago = None
        if last_seen:
            if last_seen.tzinfo is None:
                last_seen = last_seen.replace(tzinfo=timezone.utc)
            minutes_ago = round(
                (datetime.now(timezone.utc) - last_seen).total_seconds() / 60, 1
            )
        result.append({
            "bot":          bot,
            "display_name": BOT_DISPLAY.get(bot, bot),
            "status":       _bot_status(bot, row.get("last_seen")),
            "account":      row.get("account"),
            "iteration":    row.get("iteration"),
            "last_seen":    last_seen.isoformat() if last_seen else None,
            "minutes_ago":  minutes_ago,
        })
    return result


# ── GET /api/bots/positions ────────────────────────────────────────────────────

@router.get("/positions")
def positions(
    bot: str = Query("", description="Filter by bot name"),
    open_only: bool = Query(True, description="Only open positions"),
    closed_since_hours: Optional[float] = Query(
        None, description="For closed view: show only positions closed within N hours"
    ),
    limit: int = Query(100),
    current_user: dict = Depends(get_current_user),
):
    conn = get_pg()
    cur = conn.cursor()

    conditions: list[str] = []
    params: list = []

    if bot:
        conditions.append("bot = %s")
        params.append(bot)

    if open_only:
        conditions.append("is_open = TRUE")
    elif closed_since_hours is not None:
        # Recently-closed only
        conditions.append("is_open = FALSE")
        conditions.append("closed_at > NOW() - (%s * interval '1 hour')")
        params.append(closed_since_hours)

    where = ("WHERE " + " AND ".join(conditions)) if conditions else ""
    params.append(limit)

    cur.execute(
        f"""SELECT id, bot, account, symbol, direction, trigger, strategy,
                   entry_price, sl, tp, volume, timeframe,
                   confidence, rsi, atr, h1_trend, adx,
                   ticket, trail_count, is_open,
                   exit_reason, exit_rsi, opened_at, closed_at, received_at,
                   sl_updated_at, details
            FROM bot_positions {where}
            ORDER BY received_at DESC
            LIMIT %s""",
        params,
    )
    rows = []
    for r in cur.fetchall():
        row = dict(r)
        for col in ("opened_at", "closed_at", "received_at", "sl_updated_at"):
            if row.get(col):
                row[col] = row[col].isoformat()
        row["display_name"] = BOT_DISPLAY.get(row["bot"], row["bot"])
        rows.append(row)

    cur.close()
    conn.close()
    return rows


# ── GET /api/bots/events ───────────────────────────────────────────────────────

@router.get("/events")
def events(
    bot: str = Query("", description="Filter by bot name"),
    event_type: str = Query("", description="Filter by event type"),
    limit: int = Query(100),
    page: int = Query(1),
    current_user: dict = Depends(get_current_user),
):
    conn = get_pg()
    cur = conn.cursor()

    conditions: list[str] = []
    params: list = []
    if bot:
        conditions.append("bot = %s")
        params.append(bot)
    if event_type:
        conditions.append("event_type = %s")
        params.append(event_type)

    where = ("WHERE " + " AND ".join(conditions)) if conditions else ""
    offset = (page - 1) * limit
    params.extend([limit, offset])

    cur.execute(
        f"""SELECT id, bot, event_type, account, symbol, ticket,
                   trigger, direction, entry_price, old_sl, new_sl,
                   rsi, event_timestamp, received_at
            FROM bot_events {where}
            ORDER BY received_at DESC
            LIMIT %s OFFSET %s""",
        params,
    )
    rows = []
    for r in cur.fetchall():
        row = dict(r)
        if row.get("received_at"):
            row["received_at"] = row["received_at"].isoformat()
        row["display_name"] = BOT_DISPLAY.get(row["bot"], row["bot"])
        rows.append(row)

    cur.close()
    conn.close()
    return rows


# ── GET /api/bots/stats ────────────────────────────────────────────────────────

@router.get("/stats")
def stats(current_user: dict = Depends(get_current_user)):
    """Per-bot counters: total trades, open positions, trail count, rejections."""
    conn = get_pg()
    cur = conn.cursor()

    result = {}
    for bot in BOTS:
        # Anaconda aggregates legacy hawk data too
        if bot == "anaconda":
            where = "bot IN ('anaconda', 'hawk')"
            qp: list = []
        else:
            where = "bot = %s"
            qp = [bot]

        cur.execute(f"SELECT COUNT(*) AS cnt FROM bot_positions WHERE {where}", qp)
        total_trades = cur.fetchone()["cnt"]

        cur.execute(
            f"SELECT COUNT(*) AS cnt FROM bot_positions WHERE {where} AND is_open=TRUE", qp
        )
        open_positions = cur.fetchone()["cnt"]

        cur.execute(
            f"SELECT COUNT(*) AS cnt FROM bot_events WHERE {where} AND event_type='rejected'", qp
        )
        rejections = cur.fetchone()["cnt"]

        cur.execute(
            f"SELECT COUNT(*) AS cnt FROM bot_positions WHERE {where} AND DATE(received_at) = CURRENT_DATE",
            qp,
        )
        today_trades = cur.fetchone()["cnt"]

        cur.execute(
            f"SELECT COUNT(*) AS cnt FROM bot_events WHERE {where} AND event_type='trail_update'", qp
        )
        total_trails = cur.fetchone()["cnt"]

        result[bot] = {
            "display_name":   BOT_DISPLAY.get(bot, bot),
            "total_trades":   total_trades,
            "open_positions": open_positions,
            "today_trades":   today_trades,
            "rejections":     rejections,
            "total_trails":   total_trails,
        }

    cur.close()
    conn.close()
    return result


# ── POST /api/bots/sync ────────────────────────────────────────────────────────

class SyncPosition(BaseModel):
    bot: str
    account: Optional[int] = None
    symbol: str
    direction: Optional[str] = None
    trigger: Optional[str] = None
    strategy: Optional[str] = None
    entry_price: Optional[float] = None
    sl: Optional[float] = None
    tp: Optional[float] = None
    volume: Optional[float] = None
    timeframe: Optional[str] = None
    confidence: Optional[float] = None
    rsi: Optional[float] = None
    atr: Optional[float] = None
    h1_trend: Optional[str] = None
    adx: Optional[float] = None
    ticket: Optional[int] = None


@router.post("/sync")
def sync_position(body: SyncPosition, current_user: dict = Depends(get_current_user)):
    """
    Upsert a pre-existing open position that missed its trade webhook.
    Matches on ticket if provided, else (bot, symbol) most-recent open row.
    Creates a new row if no match found.
    """
    conn = get_pg()
    cur = conn.cursor()

    pos_id = None
    if body.ticket:
        cur.execute(
            "SELECT id FROM bot_positions WHERE ticket=%s AND is_open=TRUE LIMIT 1",
            (body.ticket,),
        )
        row = cur.fetchone()
        if row:
            pos_id = row["id"]

    if pos_id is None:
        cur.execute(
            """SELECT id FROM bot_positions
               WHERE bot=%s AND symbol=%s AND is_open=TRUE
               ORDER BY received_at DESC LIMIT 1""",
            (body.bot, body.symbol),
        )
        row = cur.fetchone()
        if row:
            pos_id = row["id"]

    if pos_id:
        cur.execute(
            """UPDATE bot_positions SET
                   account=%s, direction=%s, trigger=%s, strategy=%s,
                   entry_price=%s, sl=%s, tp=%s, volume=%s, timeframe=%s,
                   confidence=%s, rsi=%s, atr=%s, h1_trend=%s, adx=%s,
                   ticket=%s
               WHERE id=%s""",
            (
                body.account, body.direction, body.trigger, body.strategy,
                body.entry_price, body.sl, body.tp, body.volume, body.timeframe,
                body.confidence, body.rsi, body.atr, body.h1_trend, body.adx,
                body.ticket, pos_id,
            ),
        )
        action = "updated"
    else:
        cur.execute(
            """INSERT INTO bot_positions
                   (bot, account, symbol, direction, trigger, strategy,
                    entry_price, sl, tp, volume, timeframe,
                    confidence, rsi, atr, h1_trend, adx,
                    ticket, is_open, opened_at)
               VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,TRUE,NOW())
               RETURNING id""",
            (
                body.bot, body.account, body.symbol, body.direction,
                body.trigger, body.strategy, body.entry_price,
                body.sl, body.tp, body.volume, body.timeframe,
                body.confidence, body.rsi, body.atr, body.h1_trend,
                body.adx, body.ticket,
            ),
        )
        pos_id = cur.fetchone()["id"]
        action = "created"

    conn.commit()
    cur.close()
    conn.close()
    return {"status": "ok", "action": action, "id": pos_id}
