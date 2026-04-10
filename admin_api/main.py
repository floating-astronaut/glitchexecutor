import asyncio
import os

import httpx
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Query
from fastapi.middleware.cors import CORSMiddleware

from db import run_migrations, get_pg
from auth import verify_token, seed_admin
from ws import manager
from routers import dashboard, trading, clients, billing, infra, settings as settings_router
from routers import webhook, bots, oracle as oracle_router, analytics as analytics_router, ib as ib_router
from routers import control_centre as cc_router, telegram_mgmt as tg_router, admin_mgmt as admin_router

ORACLE_API_URL = os.environ.get("ORACLE_API_URL", "https://oracle.ngrok.dev")


async def _reconcile_positions():
    """
    Background task: polls Oracle's /positions endpoint every 60 s.

    Two reconciliation passes:
    1. Ticket-based: any open DB position whose ticket is NOT in Oracle's
       live list is marked RECONCILED.
    2. Ticketless: for each (bot, symbol) group with no ticket, we allow
       at most as many open rows as Oracle reports for that pair.  The
       oldest excess rows are marked RECONCILED.

    Oracle normalises bot names differently (e.g. "viper" not "viper3",
    "anaconda" covers the legacy "hawk" rows).  We handle the mapping here.
    """
    # Oracle bot-name → set of DB bot names it covers
    _ORACLE_TO_DB: dict[str, set] = {
        "viper":    {"viper3"},
        "viper3":   {"viper3"},
        "anaconda": {"anaconda", "hawk"},
        "hawk":     {"anaconda", "hawk"},
        "cobra":    {"cobra"},
        "mamba":    {"mamba"},
        "taipan":   {"taipan"},
    }

    await asyncio.sleep(30)  # Wait for startup to settle
    while True:
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.get(f"{ORACLE_API_URL}/positions")
                if resp.status_code != 200:
                    await asyncio.sleep(60)
                    continue
                oracle_data = resp.json()

            # Normalise: accept list or dict with 'positions' key
            if isinstance(oracle_data, dict):
                oracle_positions = oracle_data.get("positions", [])
            else:
                oracle_positions = oracle_data if isinstance(oracle_data, list) else []

            # Build live_tickets and live_count per (db_bot, symbol)
            live_tickets: set[int] = set()
            live_count: dict[tuple, int] = {}
            for p in oracle_positions:
                if p.get("ticket") is not None:
                    live_tickets.add(int(p["ticket"]))
                oracle_bot = p.get("bot", "")
                symbol = p.get("symbol", "")
                for db_bot in _ORACLE_TO_DB.get(oracle_bot, {oracle_bot}):
                    key = (db_bot, symbol)
                    live_count[key] = live_count.get(key, 0) + 1

            conn = get_pg()
            cur = conn.cursor()

            # ── Pass 1: ticket-based reconciliation ───────────────────────
            cur.execute(
                """SELECT id, bot, symbol, ticket
                   FROM bot_positions
                   WHERE is_open = TRUE
                     AND ticket IS NOT NULL
                     AND received_at < NOW() - INTERVAL '60 seconds'"""
            )
            ticketed_open = cur.fetchall()
            to_close = [r for r in ticketed_open if r["ticket"] not in live_tickets]

            # Track how many ticketed positions we're keeping per (bot, symbol)
            ticket_kept: dict[tuple, int] = {}
            for r in ticketed_open:
                if r["ticket"] in live_tickets:
                    key = (r["bot"], r["symbol"])
                    ticket_kept[key] = ticket_kept.get(key, 0) + 1

            # ── Pass 2: ticketless reconciliation ─────────────────────────
            cur.execute(
                """SELECT id, bot, symbol
                   FROM bot_positions
                   WHERE is_open = TRUE
                     AND ticket IS NULL
                     AND received_at < NOW() - INTERVAL '60 seconds'
                   ORDER BY bot, symbol, received_at DESC"""
            )
            ticketless_open = cur.fetchall()

            # For each (bot, symbol) group, allow at most
            # (oracle_live_count - ticket_kept_count) ticketless rows open.
            seen: dict[tuple, int] = {}
            for r in ticketless_open:
                key = (r["bot"], r["symbol"])
                seen[key] = seen.get(key, 0) + 1
                allowed = max(0, live_count.get(key, 0) - ticket_kept.get(key, 0))
                if seen[key] > allowed:
                    to_close.append(r)

            # ── Close all stale rows ──────────────────────────────────────
            for row in to_close:
                cur.execute(
                    """UPDATE bot_positions
                       SET is_open = FALSE, exit_reason = 'RECONCILED', closed_at = NOW()
                       WHERE id = %s""",
                    (row["id"],),
                )
                print(
                    f"[reconcile] Closed id={row['id']} "
                    f"bot={row['bot']} symbol={row['symbol']} "
                    f"ticket={row.get('ticket')}"
                )

            if to_close:
                conn.commit()
                await manager.broadcast({
                    "channel": "position:close",
                    "bot": "oracle",
                    "data": {"reconciled": len(to_close)},
                })

            cur.close()
            conn.close()

        except Exception as e:
            print(f"[reconcile] Error: {e}")

        await asyncio.sleep(60)

app = FastAPI(title="GlitchExecutor Admin API", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["https://dashboard.glitchexecutor.com"],
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE"],
    allow_headers=["Authorization", "Content-Type"],
)

# Routers
app.include_router(dashboard.router, prefix="/api/dashboard", tags=["dashboard"])
app.include_router(trading.router,   prefix="/api/trading",   tags=["trading"])
app.include_router(clients.router,   prefix="/api/clients",   tags=["clients"])
app.include_router(billing.router,   prefix="/api/billing",   tags=["billing"])
app.include_router(infra.router,     prefix="/api/infra",     tags=["infra"])
app.include_router(settings_router.router, prefix="/api/settings", tags=["settings"])
# Webhook — no auth required (internal bots)
app.include_router(webhook.router,         prefix="/api/trades",   tags=["webhook"])
# Bot data API — requires JWT
app.include_router(bots.router,            prefix="/api/bots",     tags=["bots"])
# Oracle coordinator API — requires JWT
app.include_router(oracle_router.router,   prefix="/api/oracle",     tags=["oracle"])
# AI Analytics — requires JWT
app.include_router(analytics_router.router, prefix="/api/analytics", tags=["analytics"])
# Interactive Brokers Gateway — requires JWT
app.include_router(ib_router.router,        prefix="/api/ib",        tags=["ib"])
app.include_router(cc_router.router,     prefix="/api/cc",    tags=["control_centre"])
app.include_router(tg_router.router,     prefix="/api/tg",    tags=["telegram_mgmt"])
app.include_router(admin_router.router,  prefix="/api/admin", tags=["admin_mgmt"])

# Auth router is included separately at /auth prefix
from routers import auth as auth_router
app.include_router(auth_router.router, prefix="/auth", tags=["auth"])


@app.on_event("startup")
async def startup():
    run_migrations()
    conn = get_pg()
    seed_admin(conn)
    conn.close()
    # Start Oracle position reconciliation background task
    asyncio.create_task(_reconcile_positions())


@app.get("/health")
def health():
    return {"status": "ok", "service": "admin_api"}


@app.websocket("/ws")
async def ws_endpoint(websocket: WebSocket, token: str = Query("")):
    try:
        verify_token(token)
    except Exception:
        await websocket.close(code=4001)
        return
    await manager.connect(websocket)
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        manager.disconnect(websocket)
