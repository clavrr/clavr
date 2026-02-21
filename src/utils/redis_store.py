"""
Redis Persistence Helper

Provides a lightweight wrapper for services that need optional Redis
persistence.  Falls back to a plain in-memory dict so services always
work even when Redis is unavailable (e.g., in tests or local dev).

Usage:
    store = RedisBackedStore(prefix="sprint_velocity")
    store.set("user:1:cycles", data_list)
    data = store.get("user:1:cycles")
"""
import json
import logging
from typing import Any, Optional

from src.utils.urls import URLs

logger = logging.getLogger(__name__)

# Default TTL: 90 days (long enough for historical sprint data)
DEFAULT_TTL_SECONDS = 60 * 60 * 24 * 90


class RedisBackedStore:
    """
    Dict-like store that persists to Redis when available.

    Every key is prefixed with ``clavr:{prefix}:`` to avoid collisions.
    Values are JSON-serialized.
    """

    def __init__(
        self,
        prefix: str,
        ttl_seconds: int = DEFAULT_TTL_SECONDS,
    ):
        self._prefix = f"clavr:{prefix}"
        self._ttl = ttl_seconds
        self._local: dict[str, Any] = {}
        self._redis = self._connect()

    # --- public API ---

    def set(self, key: str, value: Any) -> None:
        """Store a value in both local cache and Redis."""
        self._local[key] = value
        if self._redis:
            try:
                full_key = f"{self._prefix}:{key}"
                self._redis.set(full_key, json.dumps(value, default=str), ex=self._ttl)
            except Exception as exc:  # noqa: BLE001
                logger.debug(f"[RedisStore] Write failed ({key}): {exc}")

    def get(self, key: str, default: Any = None) -> Any:
        """Read a value; local cache first, then Redis."""
        if key in self._local:
            return self._local[key]
        if self._redis:
            try:
                full_key = f"{self._prefix}:{key}"
                raw = self._redis.get(full_key)
                if raw is not None:
                    value = json.loads(raw)
                    self._local[key] = value  # hydrate local cache
                    return value
            except Exception as exc:  # noqa: BLE001
                logger.debug(f"[RedisStore] Read failed ({key}): {exc}")
        return default

    def delete(self, key: str) -> None:
        """Remove a key from both caches."""
        self._local.pop(key, None)
        if self._redis:
            try:
                self._redis.delete(f"{self._prefix}:{key}")
            except Exception:  # noqa: BLE001
                pass

    def keys_for_prefix(self, sub_prefix: str) -> list[str]:
        """Return local keys that start with *sub_prefix*."""
        return [k for k in self._local if k.startswith(sub_prefix)]

    # --- internals ---

    @staticmethod
    def _connect():
        """Try to connect to Redis.  Returns None on failure."""
        try:
            import redis as _redis  # noqa: N811

            client = _redis.from_url(URLs.REDIS, decode_responses=True)
            client.ping()
            logger.info("[RedisStore] Connected to Redis")
            return client
        except Exception as exc:  # noqa: BLE001
            logger.info(f"[RedisStore] Redis unavailable, using memory only: {exc}")
            return None
