"""
cache.py — простой TTL-кэш для SOV Bot.
Кэшируем: топ пользователей, список участников, статистику.
"""
import time
import asyncio
import logging
from typing import Any, Optional, Callable

logger = logging.getLogger(__name__)


class TTLCache:
    """Thread-safe in-memory кэш с временем жизни записей."""

    def __init__(self):
        self._store: dict[str, tuple[Any, float]] = {}

    def get(self, key: str) -> Optional[Any]:
        entry = self._store.get(key)
        if entry is None:
            return None
        value, expires_at = entry
        if time.time() > expires_at:
            del self._store[key]
            return None
        return value

    def set(self, key: str, value: Any, ttl: int = 60):
        """ttl в секундах."""
        self._store[key] = (value, time.time() + ttl)

    def invalidate(self, *keys: str):
        """Сбросить конкретные ключи."""
        for key in keys:
            self._store.pop(key, None)

    def invalidate_prefix(self, prefix: str):
        """Сбросить все ключи с заданным префиксом."""
        to_delete = [k for k in self._store if k.startswith(prefix)]
        for k in to_delete:
            del self._store[k]

    def clear(self):
        self._store.clear()

    def size(self) -> int:
        return len(self._store)


# Глобальный экземпляр
cache = TTLCache()

# ── TTL константы (секунды) ──────────────────────────────────────────────────
TTL_TOP_USERS     = 120   # топ-3/10 — 2 минуты
TTL_ALL_USERS     = 60    # список участников — 1 минута
TTL_STATS         = 300   # статистика — 5 минут
TTL_ACTIVE_EVENTS = 30    # активные ивенты — 30 секунд (меняются чаще)
TTL_ANN_COUNT     = 60    # счётчик объявлений


def cached(key_fn: Callable, ttl: int = 60):
    """
    Декоратор для кэширования синхронных функций.
    key_fn(*args, **kwargs) -> str — вычисляет ключ кэша.
    """
    def decorator(func: Callable):
        def wrapper(*args, **kwargs):
            key = key_fn(*args, **kwargs)
            hit = cache.get(key)
            if hit is not None:
                return hit
            result = func(*args, **kwargs)
            cache.set(key, result, ttl)
            return result
        return wrapper
    return decorator


async def cleanup_loop():
    """Периодически чистим просроченные записи (каждые 5 минут)."""
    while True:
        await asyncio.sleep(300)
        before = cache.size()
        # TTLCache.get уже удаляет просроченные при обращении,
        # поэтому достаточно пройтись по всем ключам
        keys = list(cache._store.keys())
        for k in keys:
            cache.get(k)  # вызовет удаление если expired
        after = cache.size()
        if before != after:
            logger.debug(f"Cache cleanup: {before} → {after} entries")
