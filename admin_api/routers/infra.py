from fastapi import APIRouter, Depends, Query
from auth import get_current_user
import psutil
import docker

from db import get_ml_pg

router = APIRouter()

# Live docker containers we expect (post legacy MT5/ensemble retirement).
TARGET_CONTAINERS = [
    "glitch-postgres",
    "glitch-redis",
    "glitch-payment",
    "glitch-admin-api",
    "glitch-dashboard",
    "glitch-docker-proxy",
]

# Host services (not docker) we surface as pseudo-services. Status is derived
# from a domain-specific signal because admin_api can't reach systemctl from
# inside its container.
HOST_SERVICES = [
    {"name": "glitch-ml-collector", "type": "host", "category": "Ouroboros (cTrader)"},
]


def _ml_collector_status() -> dict:
    """Health of ml-collector inferred from ml_signals freshness."""
    try:
        conn = get_ml_pg()
        cur = conn.cursor()
        cur.execute(
            "SELECT EXTRACT(EPOCH FROM NOW() - MAX(created_at)) AS age FROM ml_signals"
        )
        age = cur.fetchone()["age"]
        cur.close()
        conn.close()
        if age is None:
            return {"status": "no_data", "health": "unknown"}
        age = int(age)
        if age <= 120:
            return {"status": "running", "health": "healthy", "age_sec": age}
        if age <= 600:
            return {"status": "running", "health": "stale", "age_sec": age}
        return {"status": "stopped", "health": "unhealthy", "age_sec": age}
    except Exception as e:
        return {"status": "unknown", "health": "unreachable", "error": str(e)}


@router.get("/services")
def services(current_user: dict = Depends(get_current_user)):
    result = []
    try:
        client = docker.from_env()
        containers = {c.name: c for c in client.containers.list(all=True)}

        for name in TARGET_CONTAINERS:
            c = containers.get(name)
            if c:
                attrs = c.attrs or {}
                state = attrs.get("State", {})
                health_status = state.get("Health", {}).get("Status", "none") if state.get("Health") else "none"
                # Image tag from the container's Config.Image (avoids a separate
                # /images/{id}/json call that the docker socket proxy blocks).
                image = (attrs.get("Config", {}) or {}).get("Image", "unknown")
                result.append({
                    "name": name,
                    "status": c.status,
                    "health": health_status,
                    "image": image,
                    "started_at": state.get("StartedAt"),
                })
            else:
                result.append({
                    "name": name,
                    "status": "not_found",
                    "health": "none",
                    "image": "unknown",
                    "started_at": None,
                })
    except Exception as e:
        return {"error": str(e), "services": []}

    # Append host-level pseudo-services (Ouroboros, etc.)
    ml = _ml_collector_status()
    result.append({
        "name": "glitch-ml-collector",
        "status": ml.get("status", "unknown"),
        "health": ml.get("health", "unknown"),
        "image": "host:systemd",
        "started_at": None,
        "type": "host",
        "category": "Ouroboros (cTrader)",
        "age_sec": ml.get("age_sec"),
    })
    return result


@router.get("/system")
def system(current_user: dict = Depends(get_current_user)):
    mem = psutil.virtual_memory()
    disk = psutil.disk_usage("/")
    return {
        "cpu_percent": psutil.cpu_percent(interval=1),
        "memory": {
            "total_gb": round(mem.total / 1e9, 2),
            "used_gb": round(mem.used / 1e9, 2),
            "percent": mem.percent,
        },
        "disk": {
            "total_gb": round(disk.total / 1e9, 2),
            "used_gb": round(disk.used / 1e9, 2),
            "percent": disk.percent,
        },
    }


@router.get("/logs")
def logs(
    service: str = Query("payment", description="Service short name (e.g. payment, ensemble)"),
    lines: int = Query(100, ge=10, le=2000),
    current_user: dict = Depends(get_current_user)
):
    container_name = f"glitch-{service}"
    try:
        client = docker.from_env()
        container = client.containers.get(container_name)
        raw = container.logs(tail=lines, timestamps=True)
        content = raw.decode("utf-8", errors="replace")
        return {"service": service, "container": container_name, "lines": lines, "content": content}
    except docker.errors.NotFound:
        return {"error": f"Container '{container_name}' not found"}
    except Exception as e:
        return {"error": str(e)}
