from fastapi import APIRouter, Depends, Query
from auth import get_current_user
import psutil
import docker

router = APIRouter()

TARGET_CONTAINERS = [
    "glitch-postgres",
    "glitch-redis",
    "glitch-ensemble",
    "glitch-telegram-bot",
    "glitch-executor",
    "glitch-payment",
    "glitch-admin-api",
]


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
                result.append({
                    "name": name,
                    "status": c.status,
                    "health": health_status,
                    "image": c.image.tags[0] if c.image.tags else "unknown",
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
