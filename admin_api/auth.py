import os
from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from jose import JWTError, jwt
from passlib.context import CryptContext

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


async def get_current_user(token: str = Depends(oauth2_scheme)) -> dict:
    return verify_token(token)


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
