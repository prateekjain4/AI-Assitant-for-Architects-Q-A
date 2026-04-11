import os
from datetime import datetime, timedelta
from typing import Optional

import bcrypt
from jose import JWTError, jwt

# ── Config ────────────────────────────────────────────────────────────────────
# Override SECRET_KEY via env var in production: export JWT_SECRET=<random 64 chars>
SECRET_KEY = os.getenv("JWT_SECRET", "bylaw-dev-secret-change-in-production-abc123xyz")
ALGORITHM  = "HS256"
ACCESS_TOKEN_EXPIRE_HOURS = 24


# ── Password helpers ──────────────────────────────────────────────────────────
def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()


def verify_password(plain: str, hashed: str) -> bool:
    return bcrypt.checkpw(plain.encode(), hashed.encode())


# ── JWT helpers ───────────────────────────────────────────────────────────────
def create_access_token(data: dict, expires_hours: Optional[int] = None) -> str:
    to_encode = data.copy()
    expire = datetime.utcnow() + timedelta(hours=expires_hours or ACCESS_TOKEN_EXPIRE_HOURS)
    to_encode["exp"] = expire
    return jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)


def decode_token(token: str) -> Optional[dict]:
    try:
        return jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
    except JWTError:
        return None
