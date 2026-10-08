import asyncio
import random
import sqlite3
from collections.abc import Awaitable, Callable
from typing import TypeVar

from sqlalchemy.exc import OperationalError as SQLAlchemyOperationalError

T = TypeVar("T")

def _is_sqlite_locked(exc: BaseException) -> bool:
    if isinstance(exc, sqlite3.OperationalError):
        return "database is locked" in str(exc).lower()
    if isinstance(exc, SQLAlchemyOperationalError):
        orig = getattr(exc, "orig", None)
        return isinstance(orig, sqlite3.OperationalError) and "database is locked" in str(orig).lower()
    return False

async def retry_sqlite_locked(fn: Callable[[], Awaitable[T]], attempts: int = 3) -> T:
    last: BaseException | None = None
    for attempt in range(attempts):
        try:
            return await fn()
        except Exception as exc:
            if not _is_sqlite_locked(exc) or attempt == attempts - 1:
                raise
            last = exc
            await asyncio.sleep(random.uniform(0.05, 0.2))
    raise last  # type: ignore[misc]

async def retry_once(fn, *args, **kwargs):
    try:
        return await fn(*args, **kwargs)
    except Exception:
        await asyncio.sleep(0.05)
        return await fn(*args, **kwargs)
