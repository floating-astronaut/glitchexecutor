"""
POST /api/trades/webhook
Receives trade events from bot servers (viper3, hawk, mamba, cobra).
Requires X-Webhook-Secret header matching TRADE_WEBHOOK_SECRET env var.
Returns HTTP 200 in < 2 seconds.
"""
import os
import hmac
import json
import time
import asyncio
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Request, HTTPException, BackgroundTasks

from db import get_pg
from ws import manager

_TRADE_WEBHOOK_SECRET = os.environ.get("TRADE_WEBHOOK_SECRET", "")

router = APIRouter()

VALID_BOTS = {"viper3", "anaconda", "hawk", "mamba", "cobra", "taipan", "oracle"}
VALID_EVENTS = {
    "trade", "rejected", "heartbeat",
    "friday_flatten", "breakeven", "trail_update", "mr_exit",
    "sync",
    # Oracle coordinator events
    "conflict", "correlation_warning", "risk_warning",
    "kill_all", "bot_stopped", "bot_started",
}

# Oracle severity map
_ORACLE_SEVERITY: dict[str, str] = {
    "kill_all":            "critical",
    "conflict":            "critical",
    "risk_warning":        "high",
    "correlation_warning": "warning",
    "bot_stopped":         "info",
    "bot_started":         "info",
}

# ── In-memory dedup ────────────────────────────────────────────────────────────
# Key = "bot:symbol:event:timestamp"  →  unix_ts when first seen
_dedup: dict[str, float] = {}
DEDUP_WINDOW = 5.0  # seconds


def _is_duplicate(bot: str, symbol: str, event: str, timestamp: str) -> bool:
    key = f"{bot}:{symbol}:{event}:{timestamp}"
    now = time.monotonic()
    # Prune expired entries
    expired = [k for k, v in _dedup.items() if now - v > DEDUP_WINDOW]
    for k in expired:
        _dedup.pop(k, None)
    if key in _dedup:
        return True
    _dedup[key] = now
    return False


# ── WebSocket broadcast helper ─────────────────────────────────────────────────
async def _emit(channel: str, bot: str, data: dict):
    await manager.broadcast({"channel": channel, "bot": bot, "data": data})


# ── DB helpers ─────────────────────────────────────────────────────────────────

def _find_open_position(cur, bot: str, symbol: str, ticket: Optional[int]):
    """Return the id of an open position matching ticket or (bot, symbol)."""
    if ticket:
        cur.execute(
            "SELECT id FROM bot_positions WHERE ticket=%s AND is_open=TRUE LIMIT 1",
            (ticket,)
        )
        row = cur.fetchone()
        if row:
            return row["id"]
    # Fallback: match by (bot, symbol), pick most recent open
    cur.execute(
        """SELECT id FROM bot_positions
           WHERE bot=%s AND symbol=%s AND is_open=TRUE
           ORDER BY received_at DESC LIMIT 1""",
        (bot, symbol)
    )
    row = cur.fetchone()
    return row["id"] if row else None


def _upsert_stub(cur, bot: str, symbol: str, ticket: int, account: Optional[int]):
    """Create a stub position for an orphan ticket."""
    cur.execute(
        """INSERT INTO bot_positions (bot, account, symbol, ticket, opened_at)
           VALUES (%s, %s, %s, %s, NOW())
           RETURNING id""",
        (bot, account, symbol, ticket)
    )
    return cur.fetchone()["id"]


def _log_event(cur, bot: str, event_type: str, data: dict):
    cur.execute(
        """INSERT INTO bot_events
               (bot, event_type, account, symbol, ticket, trigger, direction,
                entry_price, old_sl, new_sl, rsi, details, event_timestamp)
           VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
        (
            bot, event_type,
            data.get("account"),
            data.get("symbol"),
            data.get("ticket"),
            data.get("trigger"),
            data.get("direction"),
            data.get("entry_price") or data.get("price") or data.get("entry"),
            data.get("old_sl"),
            data.get("new_sl"),
            data.get("rsi"),
            json.dumps({k: v for k, v in data.items()
                        if k not in ("bot", "event", "account", "symbol", "ticket",
                                     "trigger", "direction", "price", "entry",
                                     "old_sl", "new_sl", "rsi", "timestamp")}),
            data.get("timestamp"),
        )
    )


# ── Event handlers ─────────────────────────────────────────────────────────────

async def _handle_heartbeat(data: dict):
    bot = data["bot"]
    # Capture any extra fields as details (useful for taipan session range, etc.)
    _known = {"bot", "event", "account", "iteration", "timestamp"}
    details = {k: v for k, v in data.items() if k not in _known}
    conn = get_pg()
    cur = conn.cursor()
    cur.execute(
        """INSERT INTO bot_heartbeats (bot, account, iteration, last_seen, details)
           VALUES (%s, %s, %s, NOW(), %s)
           ON CONFLICT (bot) DO UPDATE SET
               account   = EXCLUDED.account,
               iteration = EXCLUDED.iteration,
               last_seen = NOW(),
               details   = EXCLUDED.details""",
        (
            bot,
            data.get("account"),
            data.get("iteration"),
            json.dumps(details),
        )
    )
    conn.commit()
    cur.close()
    conn.close()
    await _emit("bot:heartbeat", bot, {
        "bot": bot,
        "iteration": data.get("iteration"),
        "timestamp": data.get("timestamp"),
    })


async def _handle_oracle_heartbeat(data: dict):
    """Oracle coordinator heartbeat — stores to bot_heartbeats with full details."""
    _oracle_fields = {
        "online_bots", "total_bots", "total_positions",
        "total_lots", "conflicts", "correlation_warnings",
    }
    details = {k: data[k] for k in _oracle_fields if k in data}
    conflicts            = int(data.get("conflicts", 0))
    correlation_warnings = int(data.get("correlation_warnings", 0))
    total_positions      = int(data.get("total_positions", 0))

    conn = get_pg()
    cur = conn.cursor()
    cur.execute(
        """INSERT INTO bot_heartbeats (bot, account, iteration, last_seen, details)
           VALUES ('oracle', NULL, %s, NOW(), %s)
           ON CONFLICT (bot) DO UPDATE SET
               iteration = EXCLUDED.iteration,
               last_seen = NOW(),
               details   = EXCLUDED.details""",
        (data.get("iteration"), json.dumps(details))
    )

    # ── Auto-dismiss resolved alerts ──────────────────────────────────────────
    # If Oracle now reports no conflicts, clear any stale conflict/kill_all alerts.
    if conflicts == 0:
        cur.execute(
            """UPDATE oracle_alerts SET dismissed=TRUE
               WHERE dismissed=FALSE AND event_type IN ('conflict', 'kill_all')"""
        )
    # If correlation warnings gone, dismiss those too.
    if correlation_warnings == 0:
        cur.execute(
            """UPDATE oracle_alerts SET dismissed=TRUE
               WHERE dismissed=FALSE AND event_type='correlation_warning'"""
        )
    # If positions are back to a safe level (≤ threshold of 15), dismiss risk_warnings.
    if total_positions <= 15:
        cur.execute(
            """UPDATE oracle_alerts SET dismissed=TRUE
               WHERE dismissed=FALSE AND event_type='risk_warning'"""
        )

    conn.commit()
    cur.close()
    conn.close()
    # Broadcast on oracle-specific channel (not bot:heartbeat — keeps Activity Feed clean)
    await _emit("oracle:heartbeat", "oracle", {
        "bot": "oracle",
        **details,
        "timestamp": data.get("timestamp"),
    })


async def _handle_oracle_event(data: dict):
    """Oracle non-heartbeat event — store to oracle_alerts and broadcast."""
    event = data["event"]
    severity = _ORACLE_SEVERITY.get(event, "warning")
    message = data.get("message") or data.get("reason") or ""
    _skip = {"bot", "event", "timestamp"}
    alert_details = {k: v for k, v in data.items() if k not in _skip}

    conn = get_pg()
    cur = conn.cursor()
    cur.execute(
        """INSERT INTO oracle_alerts (event_type, severity, message, details)
           VALUES (%s, %s, %s, %s) RETURNING id""",
        (event, severity, message, json.dumps(alert_details))
    )
    alert_id = cur.fetchone()["id"]
    conn.commit()
    cur.close()
    conn.close()
    await _emit("oracle:alert", "oracle", {
        "id": alert_id,
        "event_type": event,
        "severity": severity,
        "message": message,
        "timestamp": data.get("timestamp"),
    })


async def _handle_trade(data: dict):
    bot = data["bot"]
    # Capture extra fields (e.g. taipan session data) as details JSONB
    _KNOWN_TRADE = {
        "bot", "event", "account", "symbol", "direction", "trigger", "strategy",
        "entry_price", "price", "sl", "tp", "volume", "timeframe",
        "confidence", "rsi", "atr", "h1_trend", "adx", "timestamp", "ticket",
    }
    details = {k: v for k, v in data.items() if k not in _KNOWN_TRADE}
    conn = get_pg()
    cur = conn.cursor()
    cur.execute(
        """INSERT INTO bot_positions
               (bot, account, symbol, direction, trigger, strategy,
                entry_price, sl, tp, volume, timeframe,
                confidence, rsi, atr, h1_trend, adx,
                ticket, details, is_open, opened_at)
           VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,TRUE,NOW())
           RETURNING id""",
        (
            bot,
            data.get("account"),
            data.get("symbol"),
            data.get("direction"),
            data.get("trigger"),
            data.get("strategy"),
            data.get("entry_price") or data.get("price"),
            data.get("sl"),
            data.get("tp"),
            data.get("volume"),
            data.get("timeframe"),
            data.get("confidence"),
            data.get("rsi"),
            data.get("atr"),
            data.get("h1_trend"),
            data.get("adx"),
            data.get("ticket"),
            json.dumps(details) if details else None,
        )
    )
    pos_id = cur.fetchone()["id"]
    _log_event(cur, bot, "trade", data)
    conn.commit()
    cur.close()
    conn.close()
    await _emit("position:open", bot, {
        "id": pos_id,
        "bot": bot,
        "symbol": data.get("symbol"),
        "direction": data.get("direction"),
        "price": data.get("entry_price") or data.get("price"),
        "sl": data.get("sl"),
        "tp": data.get("tp"),
        "strategy": data.get("strategy"),
        "timestamp": data.get("timestamp"),
    })


async def _handle_sync(data: dict):
    """
    Sent by the bot at startup for each position already open in MT5.
    Upserts: updates if tracked, inserts if not.
    Payload is identical to 'trade'.
    """
    bot = data["bot"]
    ticket = data.get("ticket")
    symbol = data.get("symbol", "")

    conn = get_pg()
    cur = conn.cursor()

    pos_id = _find_open_position(cur, bot, symbol, ticket)

    if pos_id:
        # Already tracked — refresh SL/TP/ticket in case they changed
        cur.execute(
            """UPDATE bot_positions SET
                   sl=%s, tp=%s, ticket=COALESCE(%s, ticket),
                   entry_price=COALESCE(%s, entry_price)
               WHERE id=%s""",
            (
                data.get("sl"),
                data.get("tp"),
                ticket,
                data.get("entry_price") or data.get("price"),
                pos_id,
            )
        )
    else:
        # Not yet tracked — insert as open position
        cur.execute(
            """INSERT INTO bot_positions
                   (bot, account, symbol, direction, trigger, strategy,
                    entry_price, sl, tp, volume, timeframe,
                    confidence, rsi, atr, h1_trend, adx,
                    ticket, is_open, opened_at)
               VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,TRUE,NOW())
               RETURNING id""",
            (
                bot, data.get("account"), symbol,
                data.get("direction"), data.get("trigger"), data.get("strategy"),
                data.get("entry_price") or data.get("price"),
                data.get("sl"), data.get("tp"), data.get("volume"),
                data.get("timeframe"), data.get("confidence"), data.get("rsi"),
                data.get("atr"), data.get("h1_trend"), data.get("adx"),
                ticket,
            )
        )
        pos_id = cur.fetchone()["id"]

    conn.commit()
    cur.close()
    conn.close()
    await _emit("position:open", bot, {
        "id": pos_id,
        "bot": bot,
        "symbol": symbol,
        "direction": data.get("direction"),
        "price": data.get("entry_price") or data.get("price"),
        "sl": data.get("sl"),
        "tp": data.get("tp"),
        "ticket": ticket,
        "timestamp": data.get("timestamp"),
    })


async def _handle_rejected(data: dict):
    bot = data["bot"]
    conn = get_pg()
    cur = conn.cursor()
    _log_event(cur, bot, "rejected", data)
    conn.commit()
    cur.close()
    conn.close()
    await _emit("bot:rejected", bot, {
        "bot": bot,
        "symbol": data.get("symbol"),
        "trigger": data.get("trigger"),
        "timestamp": data.get("timestamp"),
    })


async def _handle_breakeven(data: dict):
    bot = data["bot"]
    symbol = data.get("symbol", "")
    ticket = data.get("ticket")
    new_sl = data.get("new_sl") or data.get("sl")

    conn = get_pg()
    cur = conn.cursor()
    pos_id = _find_open_position(cur, bot, symbol, ticket)

    if pos_id is None:
        pos_id = _upsert_stub(cur, bot, symbol, ticket, data.get("account"))

    updates = ["sl=%s", "sl_updated_at = NOW()"]
    params: list = [new_sl]
    if ticket:
        updates.append("ticket=%s")
        params.append(ticket)
    if data.get("entry"):
        updates.append("entry_price=%s")
        params.append(data["entry"])
    params.append(pos_id)

    cur.execute(
        f"UPDATE bot_positions SET {', '.join(updates)} WHERE id=%s",
        params
    )
    _log_event(cur, bot, "breakeven", data)
    conn.commit()
    cur.close()
    conn.close()
    await _emit("position:update", bot, {
        "id": pos_id,
        "event": "breakeven",
        "bot": bot,
        "symbol": symbol,
        "ticket": ticket,
        "new_sl": new_sl,
        "timestamp": data.get("timestamp"),
    })


async def _handle_trail_update(data: dict):
    bot = data["bot"]
    symbol = data.get("symbol", "")
    ticket = data.get("ticket")
    old_sl = data.get("old_sl")
    new_sl = data.get("new_sl")

    conn = get_pg()
    cur = conn.cursor()
    pos_id = _find_open_position(cur, bot, symbol, ticket)

    if pos_id is None:
        pos_id = _upsert_stub(cur, bot, symbol, ticket, data.get("account"))

    updates = ["sl=%s", "trail_count = trail_count + 1", "sl_updated_at = NOW()"]
    params: list = [new_sl]
    if ticket:
        updates.append("ticket=%s")
        params.append(ticket)
    params.append(pos_id)

    cur.execute(
        f"UPDATE bot_positions SET {', '.join(updates)} WHERE id=%s",
        params
    )
    _log_event(cur, bot, "trail_update", data)
    conn.commit()
    cur.close()
    conn.close()
    await _emit("position:update", bot, {
        "id": pos_id,
        "event": "trail_update",
        "bot": bot,
        "symbol": symbol,
        "ticket": ticket,
        "old_sl": old_sl,
        "new_sl": new_sl,
        "timestamp": data.get("timestamp"),
    })


async def _handle_close(data: dict, exit_reason: str):
    bot = data["bot"]
    symbol = data.get("symbol", "")
    ticket = data.get("ticket")

    conn = get_pg()
    cur = conn.cursor()
    pos_id = _find_open_position(cur, bot, symbol, ticket)

    if pos_id is None:
        pos_id = _upsert_stub(cur, bot, symbol, ticket, data.get("account"))

    cur.execute(
        """UPDATE bot_positions
           SET is_open=FALSE, exit_reason=%s, exit_rsi=%s,
               ticket=%s, closed_at=NOW()
           WHERE id=%s""",
        (exit_reason, data.get("rsi"), ticket, pos_id)
    )
    _log_event(cur, bot, data["event"], data)
    conn.commit()
    cur.close()
    conn.close()
    await _emit("position:close", bot, {
        "id": pos_id,
        "event": data["event"],
        "bot": bot,
        "symbol": symbol,
        "ticket": ticket,
        "exit_reason": exit_reason,
        "timestamp": data.get("timestamp"),
    })


# ── Main webhook endpoint ──────────────────────────────────────────────────────

EVENT_HANDLERS = {
    "heartbeat":      (_handle_heartbeat,      None),
    "trade":          (_handle_trade,          None),
    "sync":           (_handle_sync,           None),
    "rejected":       (_handle_rejected,       None),
    "breakeven":      (_handle_breakeven,      None),
    "trail_update":   (_handle_trail_update,   None),
    "friday_flatten": (_handle_close,          "FRIDAY_FLATTEN"),
    "mr_exit":        (_handle_close,          "MR_RSI_EXIT"),
}


@router.post("/webhook")
async def receive_webhook(request: Request, background: BackgroundTasks):
    incoming_secret = request.headers.get("X-Webhook-Secret", "")
    if not _TRADE_WEBHOOK_SECRET or not hmac.compare_digest(incoming_secret, _TRADE_WEBHOOK_SECRET):
        raise HTTPException(status_code=403, detail="Forbidden")

    try:
        data = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON body")

    bot = data.get("bot", "").strip()
    event = data.get("event", "").strip()

    if bot not in VALID_BOTS:
        raise HTTPException(status_code=400, detail=f"Unknown bot: '{bot}'")
    if event not in VALID_EVENTS:
        raise HTTPException(status_code=400, detail=f"Unknown event: '{event}'")

    symbol = data.get("symbol") or ""
    timestamp = data.get("timestamp") or ""

    if _is_duplicate(bot, symbol, event, timestamp):
        return {"status": "ok", "duplicate": True}

    # ── Oracle coordinator — special routing (not a trader) ────────────────────
    if bot == "oracle":
        if event == "heartbeat":
            background.add_task(_handle_oracle_heartbeat, data)
        else:
            background.add_task(_handle_oracle_event, data)
        return {"status": "ok", "bot": bot, "event": event}

    handler_info = EVENT_HANDLERS.get(event)
    if not handler_info:
        return {"status": "ok"}

    handler, extra_arg = handler_info

    # Fire handler in background to ensure < 2s response
    if extra_arg is not None:
        background.add_task(handler, data, extra_arg)
    else:
        background.add_task(handler, data)

    return {"status": "ok", "bot": bot, "event": event}
