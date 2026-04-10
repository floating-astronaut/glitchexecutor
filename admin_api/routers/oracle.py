"""
GET    /api/oracle/status              — Current Oracle coordinator state (from bot_heartbeats)
GET    /api/oracle/alerts              — Undismissed oracle alert log
DELETE /api/oracle/alerts/{id}         — Dismiss an alert
GET    /api/oracle/live/{endpoint}     — Live proxy to Oracle coordinator API
POST   /api/oracle/control/kill        — Kill all positions
POST   /api/oracle/control/stop/{bot}  — Stop a specific bot
POST   /api/oracle/control/start/{bot} — Start a specific bot
"""
import os
from datetime import datetime, timezone

import httpx
from fastapi import APIRouter, Depends, HTTPException

from auth import get_current_user
from db import get_pg

router = APIRouter()

ORACLE_API_URL = os.environ.get("ORACLE_API_URL", "https://oracle.ngrok.dev")
ORACLE_TIMEOUT = 10  # seconds

# Valid path segments for the live proxy (whitelist)
_LIVE_PATHS: dict[str, str] = {
    "dashboard":   "/dashboard",
    "positions":   "/positions",
    "conflicts":   "/conflicts",
    "correlation": "/correlation",
    "risk":        "/risk",
    "bots":        "/bots",
}


# ── Stored state endpoints ─────────────────────────────────────────────────────

@router.get("/status")
def oracle_status(user=Depends(get_current_user)):
    conn = get_pg()
    cur = conn.cursor()
    cur.execute("SELECT * FROM bot_heartbeats WHERE bot='oracle' LIMIT 1")
    row = cur.fetchone()

    # Always use the dashboard's own reconciled open-position count —
    # Oracle's heartbeat total_positions can lag behind reality.
    cur.execute("SELECT COUNT(*) AS cnt FROM bot_positions WHERE is_open = TRUE")
    db_positions = cur.fetchone()["cnt"]

    cur.close()
    conn.close()

    if not row:
        return {
            "online":               False,
            "online_bots":          0,
            "total_bots":           0,
            "total_positions":      db_positions,
            "total_lots":           0.0,
            "conflicts":            0,
            "correlation_warnings": 0,
            "last_seen":            None,
            "minutes_ago":          None,
        }

    details = row["details"] or {}
    last_seen = row["last_seen"]
    minutes_ago: float | None = None
    online = False

    if last_seen:
        delta_s = (datetime.now(timezone.utc) - last_seen).total_seconds()
        minutes_ago = round(delta_s / 60, 1)
        online = delta_s < 120  # stale if > 2 minutes

    return {
        "online":               online,
        "online_bots":          details.get("online_bots", 0),
        "total_bots":           details.get("total_bots", 0),
        "total_positions":      db_positions,          # from reconciled DB, not stale heartbeat
        "total_lots":           details.get("total_lots", 0.0),
        "conflicts":            details.get("conflicts", 0),
        "correlation_warnings": details.get("correlation_warnings", 0),
        "last_seen":            last_seen.isoformat() if last_seen else None,
        "minutes_ago":          minutes_ago,
    }


@router.get("/alerts")
def oracle_alerts(user=Depends(get_current_user)):
    conn = get_pg()
    cur = conn.cursor()
    cur.execute(
        """SELECT id, event_type, severity, message, details, received_at
           FROM oracle_alerts
           WHERE dismissed = FALSE
           ORDER BY received_at DESC
           LIMIT 100"""
    )
    rows = cur.fetchall()
    cur.close()
    conn.close()
    return [dict(r) for r in rows]


@router.delete("/alerts")
def dismiss_all_oracle_alerts(user=Depends(get_current_user)):
    """Dismiss all undismissed oracle alerts at once."""
    conn = get_pg()
    cur = conn.cursor()
    cur.execute("UPDATE oracle_alerts SET dismissed=TRUE WHERE dismissed=FALSE")
    count = cur.rowcount
    conn.commit()
    cur.close()
    conn.close()
    return {"status": "ok", "dismissed": count}


@router.delete("/alerts/{alert_id}")
def dismiss_oracle_alert(alert_id: int, user=Depends(get_current_user)):
    conn = get_pg()
    cur = conn.cursor()
    cur.execute(
        "UPDATE oracle_alerts SET dismissed=TRUE WHERE id=%s AND dismissed=FALSE",
        (alert_id,),
    )
    if cur.rowcount == 0:
        conn.close()
        raise HTTPException(status_code=404, detail="Alert not found or already dismissed")
    conn.commit()
    cur.close()
    conn.close()
    return {"status": "ok"}


# ── Live proxy endpoints ────────────────────────────────────────────────────────

@router.get("/live/{endpoint}")
def oracle_live(endpoint: str, user=Depends(get_current_user)):
    """
    Proxy a GET request to the Oracle coordinator API.
    Valid endpoints: dashboard, positions, conflicts, correlation, risk, bots
    """
    path = _LIVE_PATHS.get(endpoint)
    if path is None:
        raise HTTPException(status_code=404, detail=f"Unknown live endpoint: '{endpoint}'")
    try:
        resp = httpx.get(f"{ORACLE_API_URL}{path}", timeout=ORACLE_TIMEOUT)
        return resp.json()
    except httpx.TimeoutException:
        raise HTTPException(status_code=504, detail="Oracle coordinator timed out")
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Oracle coordinator unreachable: {e}")


# ── Control endpoints ───────────────────────────────────────────────────────────

@router.post("/control/kill")
def oracle_kill_all(user=Depends(get_current_user)):
    """Send kill-all command to Oracle coordinator (closes all open positions)."""
    try:
        resp = httpx.post(f"{ORACLE_API_URL}/kill", timeout=ORACLE_TIMEOUT)
        if resp.status_code >= 400:
            raise HTTPException(status_code=resp.status_code, detail=resp.text)
        return resp.json()
    except HTTPException:
        raise
    except httpx.TimeoutException:
        raise HTTPException(status_code=504, detail="Oracle coordinator timed out")
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Oracle coordinator unreachable: {e}")


@router.post("/control/stop/{bot}")
def oracle_stop_bot(bot: str, user=Depends(get_current_user)):
    """Send stop command for a specific bot to Oracle coordinator."""
    try:
        resp = httpx.post(f"{ORACLE_API_URL}/stop/{bot}", timeout=ORACLE_TIMEOUT)
        if resp.status_code >= 400:
            raise HTTPException(status_code=resp.status_code, detail=resp.text)
        return resp.json()
    except HTTPException:
        raise
    except httpx.TimeoutException:
        raise HTTPException(status_code=504, detail="Oracle coordinator timed out")
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Oracle coordinator unreachable: {e}")


@router.post("/control/start/{bot}")
def oracle_start_bot(bot: str, user=Depends(get_current_user)):
    """Send start command for a specific bot to Oracle coordinator."""
    try:
        resp = httpx.post(f"{ORACLE_API_URL}/start/{bot}", timeout=ORACLE_TIMEOUT)
        if resp.status_code >= 400:
            raise HTTPException(status_code=resp.status_code, detail=resp.text)
        return resp.json()
    except HTTPException:
        raise
    except httpx.TimeoutException:
        raise HTTPException(status_code=504, detail="Oracle coordinator timed out")
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Oracle coordinator unreachable: {e}")
