import hashlib
import hmac
import logging
import secrets
import time
from collections import defaultdict, deque
from contextvars import ContextVar
from datetime import datetime, timedelta, timezone
from pathlib import Path

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerifyMismatchError
from fastapi import Depends, HTTPException, Request, Response
from sqlalchemy import delete, func, select

from app.core.config import get_settings
from app.db.session import SessionLocal
from app.modules.auth.orm.auth_session import AuthSession
from app.modules.auth.orm.user import User

COOKIE = "ra_session"
CSRF_COOKIE = "ra_csrf"
IDLE = timedelta(hours=12)
ABSOLUTE = timedelta(days=7)
_hasher = PasswordHasher()
_failures: dict[str, deque[float]] = defaultdict(deque)
_active_user_id: ContextVar[str | None] = ContextVar("active_user_id", default=None)


def owner_id() -> str:
    owner = _active_user_id.get()
    if owner is None:
        raise HTTPException(401, "Authentication required")
    return owner


def now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def digest(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def password_hash(password: str) -> str:
    if len(password) < 12 or len(password) > 1024:
        raise HTTPException(422, "Password must contain 12 to 1024 characters")
    return _hasher.hash(password)


def allowed_attempt(key: str) -> None:
    attempts = _failures[key]
    while attempts and attempts[0] < time.monotonic() - 900:
        attempts.popleft()
    if len(attempts) >= 5:
        raise HTTPException(429, "Too many attempts; try again later")


def failed_attempt(key: str) -> None:
    _failures[key].append(time.monotonic())


def setup_token_file() -> Path:
    url = get_settings().database_url
    if not url.startswith("sqlite"):
        raise RuntimeError("Local setup token requires SQLite")
    from sqlalchemy.engine import make_url

    database = make_url(url).database
    if not database or database == ":memory:":
        raise RuntimeError("Persistent database required for bootstrap")
    return Path(database).resolve().parent / "setup-token"


async def prepare_setup_token() -> None:
    async with SessionLocal() as db:
        if await db.scalar(select(func.count(User.id))):
            return
    path = setup_token_file()
    if path.exists():
        return
    token = secrets.token_urlsafe(32)
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with path.open("x", encoding="utf-8") as stream:
            stream.write(digest(token))
    except FileExistsError:
        return
    try:
        path.chmod(0o600)
    except OSError:
        logging.warning("Could not restrict setup-token file permissions; check its ACL")
    logging.warning("ONE-TIME FIRST-ADMIN SETUP TOKEN: %s", token)


def check_origin(request: Request) -> None:
    origin = request.headers.get("origin")
    if origin and origin not in get_settings().cors_allow_origins:
        raise HTTPException(403, "Origin not allowed")


def csrf_protect(request: Request) -> None:
    check_origin(request)
    if request.method in {"POST", "PUT", "PATCH", "DELETE"}:
        token = request.cookies.get(CSRF_COOKIE)
        header = request.headers.get("x-csrf-token")
        if not token or not header or not hmac.compare_digest(token, header):
            raise HTTPException(403, "CSRF token missing or invalid")


async def current_user(request: Request) -> User:
    check_origin(request)
    token = request.cookies.get(COOKIE)
    if not token:
        raise HTTPException(401, "Authentication required")
    async with SessionLocal() as db:
        record = await db.get(AuthSession, digest(token))
        if not record:
            raise HTTPException(401, "Authentication required")
        instant = now()
        if record.idle_expires_at <= instant or record.absolute_expires_at <= instant:
            await db.delete(record)
            await db.commit()
            raise HTTPException(401, "Session expired")
        user = await db.get(User, record.user_id)
        if not user:
            raise HTTPException(401, "Authentication required")
        if request.method in {"POST", "PUT", "PATCH", "DELETE"}:
            csrf_protect(request)
        record.idle_expires_at = min(instant + IDLE, record.absolute_expires_at)
        await db.commit()
        _active_user_id.set(user.id)
        return user


async def admin_user(user: User = Depends(current_user)) -> User:
    if not user.is_admin:
        raise HTTPException(403, "Administrator required")
    return user


async def issue_session(response: Response, user_id: str) -> None:
    token = secrets.token_urlsafe(48)
    instant = now()
    async with SessionLocal() as db:
        db.add(AuthSession(token_hash=digest(token), user_id=user_id, idle_expires_at=instant + IDLE, absolute_expires_at=instant + ABSOLUTE))
        await db.commit()
    response.set_cookie(COOKIE, token, httponly=True, secure=get_settings().cookie_secure, samesite="lax", max_age=int(ABSOLUTE.total_seconds()), path="/")


async def revoke_session(token: str | None, user_id: str | None = None) -> None:
    async with SessionLocal() as db:
        if user_id:
            await db.execute(delete(AuthSession).where(AuthSession.user_id == user_id))
        elif token:
            await db.execute(delete(AuthSession).where(AuthSession.token_hash == digest(token)))
        await db.commit()


def clear_session(response: Response) -> None:
    response.delete_cookie(COOKIE, path="/")


def verify_password(user: User | None, password: str) -> bool:
    if not user or not user.password_hash:
        _hasher.hash(password)
        return False
    try:
        return _hasher.verify(user.password_hash, password)
    except (VerifyMismatchError, InvalidHashError):
        return False
