import os
import logging
from datetime import datetime, timezone
from fastapi import APIRouter, HTTPException, Depends, Request, status
from pydantic import BaseModel

import redis as redis_lib

from auth import (
    verify_password, create_token, get_current_user, hash_password
)
from db import get_pg

logger = logging.getLogger("AdminAuth")

router = APIRouter()

# ─── Redis-based brute force protection ──────────────────────────────────────
_redis = redis_lib.Redis(
    host=os.environ.get("REDIS_HOST", "redis"),
    port=int(os.environ.get("REDIS_PORT", 6379)),
    decode_responses=True,
)

MAX_LOGIN_ATTEMPTS = 5
LOCKOUT_SECONDS = 900  # 15 minutes


def _check_lockout(email: str) -> tuple:
    """Return (is_locked, remaining_seconds)."""
    key = f"login_lockout:{email}"
    ttl = _redis.ttl(key)
    if ttl and ttl > 0:
        return True, ttl
    return False, 0


def _record_failed_attempt(email: str):
    """Increment fail counter; lock account after MAX_LOGIN_ATTEMPTS."""
    key = f"login_fails:{email}"
    fails = _redis.incr(key)
    _redis.expire(key, LOCKOUT_SECONDS)
    if fails >= MAX_LOGIN_ATTEMPTS:
        _redis.setex(f"login_lockout:{email}", LOCKOUT_SECONDS, "1")
        _redis.delete(key)
        logger.warning(f"Account locked out: {email} ({MAX_LOGIN_ATTEMPTS} failed attempts)")


def _clear_failed_attempts(email: str):
    """Clear fail counter on successful login."""
    _redis.delete(f"login_fails:{email}")
    _redis.delete(f"login_lockout:{email}")


class LoginRequest(BaseModel):
    email: str
    password: str


class CreateUserRequest(BaseModel):
    email: str
    password: str
    role: str = "admin"


@router.post("/login")
def login(body: LoginRequest):
    # ── Check lockout BEFORE hitting the database ──
    locked, remaining = _check_lockout(body.email)
    if locked:
        logger.warning(f"Login attempt on locked account: {body.email}")
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=f"Account temporarily locked. Try again in {remaining} seconds.",
        )

    conn = get_pg()
    cur = conn.cursor()
    cur.execute(
        "SELECT id, email, password_hash, role, is_active FROM admin_users WHERE email=%s",
        (body.email,)
    )
    user = cur.fetchone()
    if not user or not verify_password(body.password, user["password_hash"]):
        _record_failed_attempt(body.email)
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid credentials")
    if not user["is_active"]:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Account disabled")
    # ── Success — clear any failed attempts ──
    _clear_failed_attempts(body.email)
    # Update last_login
    cur.execute(
        "UPDATE admin_users SET last_login=%s WHERE id=%s",
        (datetime.now(timezone.utc), user["id"])
    )
    conn.commit()
    cur.close()
    conn.close()
    token = create_token(user["email"], user["role"])
    return {
        "access_token": token,
        "token_type": "bearer",
        "user": {"email": user["email"], "role": user["role"]}
    }


@router.get("/me")
def me(current_user: dict = Depends(get_current_user)):
    return current_user
