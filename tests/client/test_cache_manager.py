"""Unit tests for cache manager."""

import asyncio
from datetime import datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from client.cache.cache_manager import CacheEntry, CacheManager


class TestCacheEntry:
    """Tests for CacheEntry dataclass."""

    def test_cache_entry_creation(self):
        """Test creating a cache entry with generic type support."""
        data = ["chat1", "chat2"]
        timestamp = datetime.now()
        entry = CacheEntry(data=data, timestamp=timestamp)

        assert entry.data == data
        assert entry.timestamp == timestamp

    def test_cache_entry_generic_types(self):
        """Test cache entry works with different data types."""
        # Test with list
        list_entry = CacheEntry(data=[1, 2, 3], timestamp=datetime.now())
        assert isinstance(list_entry.data, list)

        # Test with dict
        dict_entry = CacheEntry(data={"key": "value"}, timestamp=datetime.now())
        assert isinstance(dict_entry.data, dict)

        # Test with string
        str_entry = CacheEntry(data="test", timestamp=datetime.now())
        assert isinstance(str_entry.data, str)


class TestCacheManager:
    """Tests for CacheManager class."""

    def test_initialization(self):
        """Test cache manager initialization with default and custom values."""
        # Default values
        manager = CacheManager()
        assert manager._refresh_interval == 30
        assert manager._max_age == 300
        assert manager._cache == {}
        assert manager._active is False

        # Custom values
        manager = CacheManager(refresh_interval=60, max_age=600)
        assert manager._refresh_interval == 60
        assert manager._max_age == 600

    @pytest.mark.asyncio
    async def test_get_cache_miss(self):
        """Test get() triggers fetch function on cache miss."""
        manager = CacheManager()
        fetch_fn = AsyncMock(return_value=["data1", "data2"])

        result = await manager.get("test_key", fetch_fn)

        assert result == ["data1", "data2"]
        fetch_fn.assert_called_once()
        assert "test_key" in manager._cache
        assert manager._cache["test_key"].data == ["data1", "data2"]

    @pytest.mark.asyncio
    async def test_get_cache_hit_fresh(self):
        """Test get() returns cached data within freshness threshold (< 5 minutes)."""
        manager = CacheManager(max_age=300)  # 5 minutes
        fetch_fn = AsyncMock(return_value=["new_data"])

        # Pre-populate cache with fresh data
        manager._cache["test_key"] = CacheEntry(
            data=["cached_data"], timestamp=datetime.now()
        )

        result = await manager.get("test_key", fetch_fn)

        assert result == ["cached_data"]
        fetch_fn.assert_not_called()  # Should not fetch if cache is fresh

    @pytest.mark.asyncio
    async def test_get_cache_stale(self):
        """Test get() fetches fresh data when cache is stale (> 5 minutes)."""
        manager = CacheManager(max_age=300)  # 5 minutes
        fetch_fn = AsyncMock(return_value=["fresh_data"])

        # Pre-populate cache with stale data (6 minutes old)
        stale_timestamp = datetime.now() - timedelta(minutes=6)
        manager._cache["test_key"] = CacheEntry(
            data=["stale_data"], timestamp=stale_timestamp
        )

        result = await manager.get("test_key", fetch_fn)

        assert result == ["fresh_data"]
        fetch_fn.assert_called_once()
        assert manager._cache["test_key"].data == ["fresh_data"]

    @pytest.mark.asyncio
    async def test_get_returns_within_100ms(self):
        """Test cache hit returns data within 100ms (performance requirement)."""
        manager = CacheManager()

        # Pre-populate cache
        manager._cache["test_key"] = CacheEntry(
            data=["cached_data"], timestamp=datetime.now()
        )

        fetch_fn = AsyncMock()

        # Measure time
        start = datetime.now()
        result = await manager.get("test_key", fetch_fn)
        elapsed = (datetime.now() - start).total_seconds() * 1000  # Convert to ms

        assert result == ["cached_data"]
        assert elapsed < 100  # Should return within 100ms

    @pytest.mark.asyncio
    async def test_background_refresh_updates_cache(self):
        """Test background refresh updates cache every 30 seconds."""
        manager = CacheManager(refresh_interval=1, max_age=300)  # 1 second for testing
        fetch_fn = AsyncMock(side_effect=[["data1"], ["data2"], ["data3"]])
        on_update = MagicMock()

        # Start background refresh
        manager.start_background_refresh("test_key", fetch_fn, on_update)

        # Wait for multiple refresh cycles
        await asyncio.sleep(2.5)  # Should trigger 2 refreshes

        # Stop refresh
        manager.stop_background_refresh()

        # Verify fetch was called multiple times
        assert fetch_fn.call_count >= 2
        # Verify on_update callback was called
        assert on_update.call_count >= 2

    @pytest.mark.asyncio
    async def test_background_refresh_handles_errors(self):
        """Test background refresh continues after fetch failures."""
        manager = CacheManager(refresh_interval=1, max_age=300)
        fetch_fn = AsyncMock(side_effect=[Exception("Fetch failed"), ["data2"]])
        on_update = MagicMock()

        manager.start_background_refresh("test_key", fetch_fn, on_update)

        # Wait for refresh cycles
        await asyncio.sleep(2.5)

        manager.stop_background_refresh()

        # Should have attempted multiple fetches despite first failure
        assert fetch_fn.call_count >= 2

    @pytest.mark.asyncio
    async def test_start_background_refresh_activates_task(self):
        """Test start_background_refresh creates and activates refresh task."""
        manager = CacheManager()
        fetch_fn = AsyncMock(return_value=["data"])
        on_update = MagicMock()

        assert manager._active is False
        assert manager._refresh_task is None

        manager.start_background_refresh("test_key", fetch_fn, on_update)

        assert manager._active is True
        assert manager._refresh_task is not None
        assert "test_key" in manager._refresh_callbacks
        assert "test_key" in manager._on_update_callbacks

        manager.stop_background_refresh()

    @pytest.mark.asyncio
    async def test_stop_background_refresh(self):
        """Test stop_background_refresh cleans up tasks and callbacks."""
        manager = CacheManager(refresh_interval=1)
        fetch_fn = AsyncMock(return_value=["data"])
        on_update = MagicMock()

        manager.start_background_refresh("test_key", fetch_fn, on_update)
        assert manager._active is True

        manager.stop_background_refresh()

        assert manager._active is False
        assert manager._refresh_callbacks == {}
        assert manager._on_update_callbacks == {}

    def test_invalidate(self):
        """Test invalidate() removes specific cache entry."""
        manager = CacheManager()
        manager._cache["key1"] = CacheEntry(data=["data1"], timestamp=datetime.now())
        manager._cache["key2"] = CacheEntry(data=["data2"], timestamp=datetime.now())

        manager.invalidate("key1")

        assert "key1" not in manager._cache
        assert "key2" in manager._cache

    def test_invalidate_nonexistent_key(self):
        """Test invalidate() handles nonexistent keys gracefully."""
        manager = CacheManager()

        # Should not raise exception
        manager.invalidate("nonexistent_key")

    def test_clear(self):
        """Test clear() removes all cache entries."""
        manager = CacheManager()
        manager._cache["key1"] = CacheEntry(data=["data1"], timestamp=datetime.now())
        manager._cache["key2"] = CacheEntry(data=["data2"], timestamp=datetime.now())

        manager.clear()

        assert manager._cache == {}

    @pytest.mark.asyncio
    async def test_multiple_keys_background_refresh(self):
        """Test background refresh handles multiple cache keys."""
        manager = CacheManager(refresh_interval=1)
        fetch_fn1 = AsyncMock(return_value=["data1"])
        fetch_fn2 = AsyncMock(return_value=["data2"])
        on_update1 = MagicMock()
        on_update2 = MagicMock()

        manager.start_background_refresh("key1", fetch_fn1, on_update1)
        manager.start_background_refresh("key2", fetch_fn2, on_update2)

        await asyncio.sleep(1.5)

        manager.stop_background_refresh()

        # Both keys should be refreshed
        assert fetch_fn1.call_count >= 1
        assert fetch_fn2.call_count >= 1
        assert on_update1.call_count >= 1
        assert on_update2.call_count >= 1

    @pytest.mark.asyncio
    async def test_cache_freshness_threshold_exactly_5_minutes(self):
        """Test cache at exactly 5-minute threshold is considered stale."""
        manager = CacheManager(max_age=300)  # Exactly 5 minutes
        fetch_fn = AsyncMock(return_value=["fresh_data"])

        # Cache entry exactly 5 minutes old
        timestamp = datetime.now() - timedelta(seconds=300)
        manager._cache["test_key"] = CacheEntry(
            data=["old_data"], timestamp=timestamp
        )

        result = await manager.get("test_key", fetch_fn)

        # Should fetch fresh data since cache is at threshold
        assert result == ["fresh_data"]
        fetch_fn.assert_called_once()
