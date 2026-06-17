from datetime import datetime, timedelta
from typing import Optional

from fastapi import HTTPException, Request, status
import jwt
from jwt import PyJWTError

from app.config import settings

ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 60 * 24


class AdminRedirect(Exception):
    pass


def create_access_token(data: dict, expires_delta: Optional[timedelta] = None) -> str:
    to_encode = data.copy()
    expire = datetime.utcnow() + (expires_delta or timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES))
    to_encode["exp"] = expire
    return jwt.encode(to_encode, settings.jwt_secret, algorithm=ALGORITHM)


def decode_token(token: str) -> Optional[dict]:
    try:
        return jwt.decode(token, settings.jwt_secret, algorithms=[ALGORITHM])
    except PyJWTError:
        return None


def require_admin(request: Request):
    token = request.session.get("admin_token")
    if not token:
        raise AdminRedirect()
    payload = decode_token(token)
    if not payload or payload.get("sub") != "admin":
        raise AdminRedirect()
    return True


def require_api_token(request: Request) -> dict:
    auth = request.headers.get("Authorization", "")
    if not auth.startswith("Bearer "):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Missing token")
    token = auth.removeprefix("Bearer ").strip()
    payload = decode_token(token)
    if not payload or payload.get("sub") != "admin":
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token")
    return payload
