import os
from datetime import datetime, timezone
from fastapi import APIRouter, Depends, HTTPException, Request, Query
import docker
import psutil
import redis as redis_lib

from auth import get_current_user
from db import get_pg, log_audit

router = APIRouter()

TARGET_CONTAINERS = [
    "glitch-postgres",
    "glitch-redis",
    "glitch-ensemble",
    "glitch-telegram-bot",
    "glitch-executor",
    "glitch-payment",
    "glitch-admin-api",
    "glitch-dashboard",
]

RESTARTABLE = set(TARGET_CONTAINERS)


def _uptime_seconds(started_at_str: str) -> int:
    if not started_at_str:
        return 0
    try:
        # Docker returns RFC3339 like "2026-03-13T07:48:47.123456789Z"
        ts = started_at_str[:26].rstrip("Z").replace("T", " ")
        started = datetime.fromisoformat(ts)
        return max(0, int((datetime.utcnow() - started).total_seconds()))
    except Exception:
        return 0


@router.get("/containers")
def containers(current_user: dict = Depends(get_current_user)):
    result = []
    try:
        client = docker.from_env()
        all_containers = {c.name: c for c in client.containers.list(all=True)}
    except Exception as e:
        return {"error": str(e), "containers": []}

    for name in TARGET_CONTAINERS:
        c = all_containers.get(name)
        if not c:
            result.append({
                "name": name, "status": "not_found", "health": "none",
                "started_at": None, "uptime_seconds": 0,
                "cpu_percent": 0.0, "mem_mb": 0.0, "image": "unknown",
            })
            continue

        attrs = c.attrs or {}
        state = attrs.get("State", {})
        health = "none"
        if state.get("Health"):
            health = state["Health"].get("Status", "none")
        started_at = state.get("StartedAt")

        cpu_pct = 0.0
        mem_mb = 0.0
        try:
            stats = c.stats(stream=False)
            cpu_delta = (
                stats["cpu_stats"]["cpu_usage"]["total_usage"]
                - stats["precpu_stats"]["cpu_usage"]["total_usage"]
            )
            sys_delta = (
                stats["cpu_stats"].get("system_cpu_usage", 0)
                - stats["precpu_stats"].get("system_cpu_usage", 0)
            )
            num_cpus = stats["cpu_stats"].get("online_cpus", 1)
            if sys_delta > 0:
                cpu_pct = round((cpu_delta / sys_delta) * num_cpus * 100.0, 1)
            mem_mb = round(stats["memory_stats"].get("usage", 0) / 1e6, 1)
        except Exception:
            pass

        result.append({
            "name": name,
            "status": c.status,
            "health": health,
            "image": c.image.tags[0] if c.image.tags else "unknown",
            "started_at": started_at,
            "uptime_seconds": _uptime_seconds(started_at),
            "cpu_percent": cpu_pct,
            "mem_mb": mem_mb,
        })

    return result


@router.post("/containers/{name}/restart")
def restart_container(
    name: str,
    request: Request,
    current_user: dict = Depends(get_current_user),
):
    if name not in RESTARTABLE:
        raise HTTPException(status_code=400, detail="Container not in allowlist")
    try:
        client = docker.from_env()
        c = client.containers.get(name)
        c.restart(timeout=15)
    except docker.errors.NotFound:
        raise HTTPException(status_code=404, detail="Container not found")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

    log_audit(
        current_user["email"], "restart_container", "container", name, {},
        request.client.host if request.client else None,
    )
    return {"success": True, "container": name}


@router.get("/system")
def system(current_user: dict = Depends(get_current_user)):
    mem = psutil.virtual_memory()
    disk = psutil.disk_usage("/")
    return {
        "cpu_percent": psutil.cpu_percent(interval=0.5),
        "memory": {
            "total_gb": round(mem.total / 1e9, 2),
            "used_gb":  round(mem.used  / 1e9, 2),
            "percent":  mem.percent,
        },
        "disk": {
            "total_gb": round(disk.total / 1e9, 2),
            "used_gb":  round(disk.used  / 1e9, 2),
            "percent":  disk.percent,
        },
    }


@router.get("/redis")
def redis_stats(current_user: dict = Depends(get_current_user)):
    try:
        rc = redis_lib.Redis(
            host=os.environ.get("REDIS_HOST", "redis"),
            port=int(os.environ.get("REDIS_PORT", 6379)),
            decode_responses=True,
        )
        info = rc.info("memory")
        return {
            "key_count":      rc.dbsize(),
            "used_memory_mb": round(info.get("used_memory",      0) / 1e6, 2),
            "peak_memory_mb": round(info.get("used_memory_peak", 0) / 1e6, 2),
            "maxmemory_mb":   round(info.get("maxmemory",        0) / 1e6, 2),
            "connected_clients": rc.info("clients").get("connected_clients", 0),
        }
    except Exception as e:
        return {"error": str(e)}


@router.get("/postgres")
def postgres_stats(current_user: dict = Depends(get_current_user)):
    try:
        conn = get_pg()
        cur = conn.cursor()
        cur.execute("SELECT count(*) AS cnt FROM pg_stat_activity")
        conn_count = cur.fetchone()["cnt"]
        cur.execute("SELECT pg_size_pretty(pg_database_size(current_database())) AS size")
        db_size = cur.fetchone()["size"]
        cur.execute("""
            SELECT COALESCE(state, 'unknown') AS state, count(*) AS cnt
            FROM pg_stat_activity GROUP BY state
        """)
        by_state = {r["state"]: r["cnt"] for r in cur.fetchall()}
        cur.close()
        conn.close()
        return {"connections": conn_count, "db_size": db_size, "by_state": by_state}
    except Exception as e:
        return {"error": str(e)}


@router.get("/logs")
def logs(
    service: str = Query("telegram-bot"),
    lines:   int = Query(50, ge=10, le=500),
    current_user: dict = Depends(get_current_user),
):
    container_name = f"glitch-{service}"
    try:
        client = docker.from_env()
        container = client.containers.get(container_name)
        raw = container.logs(tail=lines, timestamps=True)
        return {
            "service":   service,
            "container": container_name,
            "content":   raw.decode("utf-8", errors="replace"),
        }
    except docker.errors.NotFound:
        return {"error": f"Container '{container_name}' not found", "content": ""}
    except Exception as e:
        return {"error": str(e), "content": ""}
