from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Query
from fastapi.middleware.cors import CORSMiddleware

from db import run_migrations, get_pg
from auth import verify_token, seed_admin
from ws import manager
from routers import dashboard, clients, billing, infra, settings as settings_router
from routers import webhook, ib as ib_router, trade as trade_router, grow as grow_router
from routers import control_centre as cc_router, admin_mgmt as admin_router


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
