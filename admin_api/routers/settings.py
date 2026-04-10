import os
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from typing import Optional

from auth import get_current_user, hash_password
from db import get_pg, log_audit

router = APIRouter()

ENV_VARS_TO_CHECK = [
    "STRIPE_SECRET_KEY",
    "STRIPE_WEBHOOK_SECRET",
    "AWS_ACCESS_KEY_ID",
    "AWS_SECRET_ACCESS_KEY",
    "TELEGRAM_BOT_TOKEN",
    "ADMIN_JWT_SECRET",
    "ENCRYPTION_KEY",
    "SENTIMENT_LLM_KEY",
    "ORCHESTRATOR_LLM_KEY",
    "ADMIN_TOKEN",
    "CMC_API_KEY",
]


class CreateUserRequest(BaseModel):
    email: str
    password: str
    role: str = "admin"


class UpdateUserRequest(BaseModel):
    role: Optional[str] = None
    is_active: Optional[bool] = None


@router.get("/users")
def list_users(current_user: dict = Depends(get_current_user)):
    conn = get_pg()
    cur = conn.cursor()
    cur.execute(
        "SELECT id, email, role, is_active, created_at, last_login FROM admin_users ORDER BY created_at"
    )
    rows = [dict(r) for r in cur.fetchall()]
    cur.close()
    conn.close()
    return rows


@router.post("/users")
def create_user(
    body: CreateUserRequest,
    request: Request,
    current_user: dict = Depends(get_current_user)
):
    conn = get_pg()
    cur = conn.cursor()
    try:
        cur.execute(
            "INSERT INTO admin_users (email, password_hash, role) VALUES (%s, %s, %s) RETURNING id",
            (body.email, hash_password(body.password), body.role)
        )
        new_id = cur.fetchone()["id"]
        conn.commit()
    except Exception as e:
        conn.rollback()
        raise HTTPException(status_code=400, detail=str(e))
    finally:
        cur.close()
        conn.close()

    log_audit(
        current_user["email"], "create_admin_user",
        "admin_user", str(new_id),
        {"email": body.email, "role": body.role},
        request.client.host if request.client else None
    )
    return {"success": True, "id": new_id, "email": body.email}


@router.put("/users/{user_id}")
def update_user(
    user_id: int,
    body: UpdateUserRequest,
    request: Request,
    current_user: dict = Depends(get_current_user)
):
    conn = get_pg()
    cur = conn.cursor()
    updates = []
    params = []
    if body.role is not None:
        updates.append("role=%s")
        params.append(body.role)
    if body.is_active is not None:
        updates.append("is_active=%s")
        params.append(body.is_active)

    if not updates:
        raise HTTPException(status_code=400, detail="Nothing to update")

    params.append(user_id)
    cur.execute(f"UPDATE admin_users SET {', '.join(updates)} WHERE id=%s", params)
    conn.commit()
    cur.close()
    conn.close()

    log_audit(
        current_user["email"], "update_admin_user",
        "admin_user", str(user_id),
        body.dict(exclude_none=True),
        request.client.host if request.client else None
    )
    return {"success": True, "id": user_id}


@router.get("/audit")
def audit(page: int = 1, limit: int = 50, current_user: dict = Depends(get_current_user)):
    conn = get_pg()
    cur = conn.cursor()

    cur.execute("SELECT COUNT(*) AS cnt FROM audit_log")
    total = cur.fetchone()["cnt"]

    offset = (page - 1) * limit
    cur.execute("""
        SELECT a.id, u.email AS admin_email, a.action, a.target_type, a.target_id,
               a.details, a.ip_address, a.created_at
        FROM audit_log a
        LEFT JOIN admin_users u ON u.id = a.admin_user_id
        ORDER BY a.created_at DESC
        LIMIT %s OFFSET %s
    """, (limit, offset))
    rows = [dict(r) for r in cur.fetchall()]
    cur.close()
    conn.close()

    return {"total": total, "page": page, "limit": limit, "entries": rows}


@router.get("/env-status")
def env_status(current_user: dict = Depends(get_current_user)):
    return {var: bool(os.environ.get(var)) for var in ENV_VARS_TO_CHECK}
