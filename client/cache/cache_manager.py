"""Client-side cache manager with background refresh support."""

import asyncio
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Callable, Generic, TypeVar

T = TypeVar("T")


@dataclass
class CacheEntry(Generic[T]):
    """Represents a cached value with timestamp."""

    data: T
    timestamp: datetime


class CacheManager:
    """Client-side cache with background refresh for chat list queries."""

    def __init__(self, refresh_interval: int = 30, max_age: int = 300):
        """
        Initialize cache manager.

        Args:
            refresh_interval: Seconds between background refreshes (default: 30)
            max_age: Maximum age in seconds before cache is considered stale (default: 300)
        """
        self._cache: dict[str, CacheEntry] = {}
        self._refresh_interval = refresh_interval
        self._max_age = max_age
        self._refresh_task: asyncio.Task | None = None
        self._refresh_callbacks: dict[str, Callable] = {}
        self._on_update_callbacks: dict[str, Callable] = {}
        self._active = False

    async def get(self, key: str, fetch_fn: Callable) -> Any:
        """
        Get cached data or fetch if stale/missing.

        Args:
            key: Cache key (e.g., "personal_chats", "group_chats", "public_rooms")
            fetch_fn: Async function to call if cache miss or stale

        Returns:
            Cached or freshly fetched data
        """
        now = datetime.now()

        # Check if we have a cache entry
        if key in self._cache:
            entry = self._cache[key]
            age = (now - entry.timestamp).total_seconds()

            # Return cached data if fresh (within max_age threshold)
            if age < self._max_age:
                return entry.data

        # Cache miss or stale - fetch fresh data
        data = await fetch_fn()
        self._cache[key] = CacheEntry(data=data, timestamp=now)
        return data

    def start_background_refresh(
        self, key: str, fetch_fn: Callable, on_update: Callable
    ) -> None:
        """
        Register a cache key for background refresh.

        Args:
            key: Cache key to refresh
            fetch_fn: Async function to fetch fresh data
            on_update: Callback to invoke when refresh completes
        """
        self._refresh_callbacks[key] = fetch_fn
        self._on_update_callbacks[key] = on_update

        # Start the background refresh task if not already running
        if not self._active:
            self._active = True
            self._refresh_task = asyncio.create_task(self._refresh_loop())

    async def _refresh_loop(self) -> None:
        """Background task that refreshes cache entries periodically."""
        while self._active:
            await asyncio.sleep(self._refresh_interval)

            for key, fetch_fn in self._refresh_callbacks.items():
                try:
                    data = await fetch_fn()
                    self._cache[key] = CacheEntry(data=data, timestamp=datetime.now())

                    # Notify UI of update
                    if key in self._on_update_callbacks:
                        self._on_update_callbacks[key](data)
                except Exception as e:
                    # Log but continue - don't crash the refresh loop
                    print(f"Cache refresh failed for {key}: {e}")

    def stop_background_refresh(self) -> None:
        """Stop all background refresh tasks."""
        self._active = False
        if self._refresh_task:
            self._refresh_task.cancel()
            self._refresh_task = None
        self._refresh_callbacks.clear()
        self._on_update_callbacks.clear()

    def invalidate(self, key: str) -> None:
        """
        Remove a cache entry, forcing next get() to fetch fresh data.

        Args:
            key: Cache key to invalidate
        """
        if key in self._cache:
            del self._cache[key]

    def clear(self) -> None:
        """Clear all cache entries."""
        self._cache.clear()
