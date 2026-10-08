"""Bounded, owner-scoped cache of successful raw source responses."""

import logging
import time
from collections import OrderedDict
from collections.abc import Callable
from dataclasses import dataclass
from functools import lru_cache

from pydantic import TypeAdapter
from pydantic_core import PydanticSerializationError

from app.core.config import get_settings
from app.modules.papers.schemas.paper import RawPaperRecord

logger = logging.getLogger(__name__)
_records = TypeAdapter(list[RawPaperRecord])
CacheKey = tuple[str, str, str]


@dataclass(frozen=True)
class _Entry:
    data: bytes
    expires_at: float


class SourceResultCache:
    def __init__(
        self,
        ttl_seconds: float = 900,
        max_entries: int = 256,
        max_bytes: int = 32 * 1024 * 1024,
        clock: Callable[[], float] = time.monotonic,
    ):
        if ttl_seconds <= 0 or max_entries <= 0 or max_bytes <= 0:
            raise ValueError("Source cache TTL and size limits must be positive")
        self.ttl_seconds = ttl_seconds
        self.max_entries = max_entries
        self.max_bytes = max_bytes
        self._clock = clock
        self._entries: OrderedDict[CacheKey, _Entry] = OrderedDict()
        self.total_bytes = 0

    def _remove(self, key: CacheKey) -> None:
        entry = self._entries.pop(key, None)
        if entry is not None:
            self.total_bytes -= len(entry.data)

    def get(self, key: CacheKey) -> list[RawPaperRecord] | None:
        entry = self._entries.get(key)
        if entry is None:
            return None
        if entry.expires_at <= self._clock():
            self._remove(key)
            return None
        self._entries.move_to_end(key)
        return _records.validate_json(entry.data)

    def set(self, key: CacheKey, records: list[RawPaperRecord]) -> bool:
        try:
            data = _records.dump_json(records)
        except (PydanticSerializationError, TypeError, ValueError) as exc:
            logger.warning("Successful source response was not cacheable (%s)", type(exc).__name__)
            return False
        if len(data) > self.max_bytes:
            logger.warning("Successful source response exceeds the source-cache byte limit")
            return False
        now = self._clock()
        for old_key, entry in list(self._entries.items()):
            if entry.expires_at <= now:
                self._remove(old_key)
        self._remove(key)
        self._entries[key] = _Entry(data=data, expires_at=now + self.ttl_seconds)
        self.total_bytes += len(data)
        while len(self._entries) > self.max_entries or self.total_bytes > self.max_bytes:
            self._remove(next(iter(self._entries)))
        return True

    def clear(self) -> None:
        self._entries.clear()
        self.total_bytes = 0

    def __len__(self) -> int:
        return len(self._entries)


@lru_cache(maxsize=1)
def get_source_result_cache() -> SourceResultCache:
    settings = get_settings()
    return SourceResultCache(
        ttl_seconds=settings.source_cache_ttl_s,
        max_entries=settings.source_cache_max_entries,
        max_bytes=settings.source_cache_max_bytes,
    )


def clear_shared_source_result_cache() -> None:
    if get_source_result_cache.cache_info().currsize:
        get_source_result_cache().clear()
        get_source_result_cache.cache_clear()
