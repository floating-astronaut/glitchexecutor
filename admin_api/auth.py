import logging
import os
from datetime import datetime, timedelta, timezone
from typing import Optional

import httpx
from fastapi import Depends, HTTPException, Request, status
from fastapi.security import OAuth2PasswordBearer
from jose import JWTError, jwt
from passlib.context import CryptContext

logger = logging.getLogger("auth")

# Central SSO service (Flask, gunicorn @127.0.0.1:6000, fronted by sso.glitchexecutor.com).
# Validates `sso_session` cookie scoped to .glitchexecutor.com so any subdomain
# (dashboard, admin, edge, trade-app, …) can run admin_api requests authenticated
# without minting a JWT. JWT path remains for legacy clients.
SSO_VALIDATE_URL = os.environ.get(
    "SSO_VALIDATE_URL", "http://172.17.0.1:6000/auth/validate"
)
SSO_TIMEOUT_SECONDS = float(os.environ.get("SSO_TIMEOUT_SECONDS", "3.0"))

SECRET = os.environ.get("ADMIN_JWT_SECRET", "changeme-in-production")
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_HOURS = 1  # Reduced from 24h — financial platform requires short-lived tokens

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/auth/login")


def hash_password(password: str) -> str:
    return pwd_context.hash(password)


def verify_password(plain: str, hashed: str) -> bool:
    return pwd_context.verify(plain, hashed)


def create_token(email: str, role: str) -> str:
    expire = datetime.now(timezone.utc) + timedelta(hours=ACCESS_TOKEN_EXPIRE_HOURS)
    payload = {"sub": email, "role": role, "exp": expire}
    return jwt.encode(payload, SECRET, algorithm=ALGORITHM)


def verify_token(token: str) -> dict:
    """Decode token and return payload dict, raise HTTP 401 on failure."""
    try:
        payload = jwt.decode(token, SECRET, algorithms=[ALGORITHM])
        email: str = payload.get("sub")
        role: str = payload.get("role", "admin")
        if email is None:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token")
        return {"email": email, "role": role}
    except JWTError:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid or expired token")


async def get_current_user(request: Request) -> dict:
    """
    Dual-mode authentication:

      1. **SSO cookie** (preferred, used by trade-app + edge-app + future SPAs)
         — `sso_session` cookie scoped to .glitchexecutor.com. We forward it
         to SSO `/auth/validate`, which returns user info on success.

      2. **JWT bearer** (legacy, used by admin dashboard) — falls back to
         existing oauth2_scheme decoding.

    Either path resolves to the same `{email, role}` shape the rest of the
    codebase expects from `Depends(get_current_user)`. Order matters: try the
    cookie first so SPA users never need a token in localStorage.
    """
    # 1) SSO cookie path
    sso_token = request.cookies.get("sso_session")
    if sso_token:
        try:
            async with httpx.AsyncClient(timeout=SSO_TIMEOUT_SECONDS) as client:
                r = await client.get(
                    SSO_VALIDATE_URL,
                    cookies={"sso_session": sso_token},
                )
        except httpx.HTTPError as e:
            logger.warning("SSO validate unreachable: %s", e)
            r = None
        if r is not None and r.status_code == 200:
            data = r.json() or {}
            if data.get("authenticated"):
                u = data.get("user") or {}
                return {"email": u.get("email"), "role": u.get("role", "admin")}
        # SSO said 401 — fall through to JWT in case the client is the legacy dashboard
        # that has both a cookie (from another tab) and a Bearer token in flight.

    # 2) JWT bearer path (legacy)
    auth_header = request.headers.get("Authorization", "")
    if auth_header.startswith("Bearer "):
        token = auth_header.removeprefix("Bearer ").strip()
        return verify_token(token)

    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Not authenticated (no SSO cookie or Bearer token)",
        headers={"WWW-Authenticate": "Bearer"},
    )


def seed_admin(pg_conn):
    """Insert default admin user if admin_users table is empty."""
    admin_email = os.environ.get("ADMIN_EMAIL", "admin@glitchexecutor.com")
    admin_password = os.environ.get("ADMIN_PASSWORD", "admin123")
    cursor = pg_conn.cursor()
    cursor.execute("SELECT COUNT(*) AS cnt FROM admin_users")
    count = cursor.fetchone()["cnt"]
    if count == 0:
        cursor.execute(
            "INSERT INTO admin_users (email, password_hash, role) VALUES (%s, %s, %s)",
            (admin_email, hash_password(admin_password), "admin"),
        )
        pg_conn.commit()
        print(f"[seed] Created admin user: {admin_email}")
    cursor.close()
