from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Query
from fastapi.middleware.cors import CORSMiddleware

from db import run_migrations, get_pg
from auth import verify_token, seed_admin
from ws import manager
from routers import dashboard, clients, billing, infra, settings as settings_router
from routers import webhook, ib as ib_router, trade as trade_router, grow as grow_router
from routers import control_centre as cc_router, admin_mgmt as admin_router
from routers import customers as customers_router
from routers import ctrader_oauth as ctrader_oauth_router
from routers import trade_admin as trade_admin_router
from routers import infra_docs as infra_docs_router
from tasks.infra_docs_sync import start_background_sync


app = FastAPI(title="GlitchExecutor Admin API", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "https://dashboard.glitchexecutor.com",
        # trade-app.* was the original SPA hostname; renamed to trade.*
        # in May 2026 when the SPA moved to CF Pages. Keep both for the
        # short transition period (old bookmarks 301 via origin nginx,
        # but a stale tab might still issue an XHR with the old Origin).
        "https://trade.glitchexecutor.com",
        "https://trade-app.glitchexecutor.com",
    ],
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type"],
)

# Routers
app.include_router(dashboard.router, prefix="/api/dashboard", tags=["dashboard"])
app.include_router(clients.router,   prefix="/api/clients",   tags=["clients"])
app.include_router(billing.router,   prefix="/api/billing",   tags=["billing"])
app.include_router(infra.router,     prefix="/api/infra",     tags=["infra"])
app.include_router(settings_router.router, prefix="/api/settings", tags=["settings"])
# Webhook — no auth required (internal bots)
app.include_router(webhook.router,         prefix="/api/trades",   tags=["webhook"])
# Trade vertical — Ouroboros (cTrader) data from glitch_ml DB
app.include_router(trade_router.router,    prefix="/api/trade",    tags=["trade"])
# Grow vertical — Glitch Budz sales agent data from glitch_sales_agent DB
app.include_router(grow_router.router,     prefix="/api/grow",     tags=["grow"])
# Interactive Brokers Gateway — requires JWT
app.include_router(ib_router.router,        prefix="/api/ib",        tags=["ib"])
app.include_router(cc_router.router,     prefix="/api/cc",    tags=["control_centre"])
app.include_router(admin_router.router,  prefix="/api/admin", tags=["admin_mgmt"])
# Customer management — JWT-protected proxy to payment server (Grow buyers + leads now; Edge/Trade later)
app.include_router(customers_router.router, prefix="/api/customers", tags=["customers"])
# cTrader Open API OAuth — multi-tenant per-user broker connections
app.include_router(ctrader_oauth_router.router, prefix="/api/ctrader", tags=["ctrader_oauth"])
# Trade-admin proxy — forwards to glitch-trade-api /v1/admin/* with
# X-Admin-Secret injected server-side so the SPA never sees the secret.
app.include_router(trade_admin_router.router, prefix="/api/trade-admin", tags=["trade_admin"])
# Infra docs — read-only operator view of the SERVER_*.md system map.
# Populated by a 5-minute background task; manual refresh via POST
# /api/infra-docs/sync. See docs/INFRA_VIEW_PLAN.md in the SPA repo.
app.include_router(infra_docs_router.router, prefix="/api/infra-docs", tags=["infra_docs"])

# Auth router is included separately at /auth prefix
from routers import auth as auth_router
app.include_router(auth_router.router, prefix="/auth", tags=["auth"])


@app.on_event("startup")
async def startup():
    run_migrations()
    conn = get_pg()
    seed_admin(conn)
    conn.close()
    # Legacy MT5 reconciliation task removed — Ouroboros (cTrader) is the live stack.


# Schedule the infra-docs sync loop. Registers its own on_event("startup")
# hook so the periodic task is created once FastAPI is ready. 5-minute
# cadence per docs/INFRA_VIEW_PLAN.md §2.
start_background_sync(app, interval_sec=300)


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
