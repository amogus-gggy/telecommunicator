"""Integration tests for cache manager with chat list data loading."""
from __future__ import annotations

from datetime import datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from client.cache.cache_manager import CacheEntry, CacheManager


PERSONAL_ROOMS = [
    {"id": 1, "name": "alice, bob", "room_type": "personal", "owner_username": "alice",
     "member_count": 2, "is_private": False, "allow_member_invite": False, "read_only": False},
]
GROUP_ROOMS = [
    {"id": 2, "name": "dev-team", "room_type": "group", "owner_username": "alice",
     "member_count": 5, "is_private": False, "allow_member_invite": True, "read_only": False},
]
PUBLIC_ROOMS = [
    {"id": 3, "name": "general", "room_type": "public", "owner_username": "admin",
     "member_count": 20, "is_private": False, "allow_member_invite": True, "read_only": False},
]
MY_CHATS = PERSONAL_ROOMS + GROUP_ROOMS


class TestCacheChatListIntegration:
    """Integration tests for cache manager used in chat list loading."""

    @pytest.mark.asyncio
    async def test_chat_list_loads_from_cache_on_subsequent_calls(self):
        """Test that chat list returns cached data on second call without fetching."""
        manager = CacheManager(max_age=300)
        fetch_fn = AsyncMock(return_value=MY_CHATS)

        # First call - cache miss, fetches data
        result1 = await manager.get("my_chats", fetch_fn)
        assert result1 == MY_CHATS
        assert fetch_fn.call_count == 1

        # Second call - cache hit, no fetch
        result2 = await manager.get("my_chats", fetch_fn)
        assert result2 == MY_CHATS
        assert fetch_fn.call_count == 1  # Still 1, not fetched again

    @pytest.mark.asyncio
    async def test_separate_cache_entries_for_my_chats_and_public_rooms(self):
        """Test that personal/group chats and public rooms are cached separately."""
        manager = CacheManager(max_age=300)
        fetch_my = AsyncMock(return_value=MY_CHATS)
        fetch_public = AsyncMock(return_value=PUBLIC_ROOMS)

        my = await manager.get("my_chats", fetch_my)
        public = await manager.get("public_rooms", fetch_public)

        assert my == MY_CHATS
        assert public == PUBLIC_ROOMS
        assert "my_chats" in manager._cache
        assert "public_rooms" in manager._cache
        fetch_my.assert_called_once()
        fetch_public.assert_called_once()

    @pytest.mark.asyncio
    async def test_ui_updates_after_background_refresh(self):
        """Test that on_update callback is called after background refresh completes."""
        manager = CacheManager(refresh_interval=1, max_age=300)
        updated_chats = MY_CHATS + [
            {"id": 4, "name": "new-room", "room_type": "group", "owner_username": "bob",
             "member_count": 2, "is_private": False, "allow_member_invite": True, "read_only": False}
        ]
        fetch_fn = AsyncMock(return_value=updated_chats)
        on_update = MagicMock()

        manager.start_background_refresh("my_chats", fetch_fn, on_update)

        import asyncio
        await asyncio.sleep(1.5)
        manager.stop_background_refresh()

        on_update.assert_called()
        on_update.assert_called_with(updated_chats)

    @pytest.mark.asyncio
    async def test_cache_invalidation_on_room_creation(self):
        """Test that invalidating cache forces fresh fetch on next get()."""
        manager = CacheManager(max_age=300)
        fetch_fn = AsyncMock(side_effect=[MY_CHATS, MY_CHATS + GROUP_ROOMS])

        # Initial load
        result1 = await manager.get("my_chats", fetch_fn)
        assert result1 == MY_CHATS
        assert fetch_fn.call_count == 1

        # Simulate room creation - invalidate cache
        manager.invalidate("my_chats")
        assert "my_chats" not in manager._cache

        # Next get() should fetch fresh data
        result2 = await manager.get("my_chats", fetch_fn)
        assert fetch_fn.call_count == 2
        assert result2 == MY_CHATS + GROUP_ROOMS

    @pytest.mark.asyncio
    async def test_cache_invalidation_on_room_join(self):
        """Test cache invalidation when user joins a room."""
        manager = CacheManager(max_age=300)
        fetch_fn = AsyncMock(return_value=PUBLIC_ROOMS)

        await manager.get("public_rooms", fetch_fn)
        assert fetch_fn.call_count == 1

        # Simulate joining a room - invalidate public rooms cache
        manager.invalidate("public_rooms")

        await manager.get("public_rooms", fetch_fn)
        assert fetch_fn.call_count == 2

    @pytest.mark.asyncio
    async def test_stale_cache_triggers_fresh_fetch_for_chat_list(self):
        """Test that stale chat list cache (> 5 min) triggers a fresh fetch."""
        manager = CacheManager(max_age=300)
        fresh_data = MY_CHATS + GROUP_ROOMS
        fetch_fn = AsyncMock(return_value=fresh_data)

        # Populate with stale data
        stale_time = datetime.now() - timedelta(minutes=6)
        manager._cache["my_chats"] = CacheEntry(data=MY_CHATS, timestamp=stale_time)

        result = await manager.get("my_chats", fetch_fn)

        assert result == fresh_data
        fetch_fn.assert_called_once()

    @pytest.mark.asyncio
    async def test_clear_removes_all_chat_cache_entries(self):
        """Test that clear() removes all cached chat data."""
        manager = CacheManager(max_age=300)
        await manager.get("my_chats", AsyncMock(return_value=MY_CHATS))
        await manager.get("public_rooms", AsyncMock(return_value=PUBLIC_ROOMS))

        assert len(manager._cache) == 2

        manager.clear()

        assert manager._cache == {}
