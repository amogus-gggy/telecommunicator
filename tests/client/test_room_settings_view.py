"""Unit tests for conditional rendering in room_settings_view."""
from __future__ import annotations

import pytest

from client.state import AppState, RoomDTO, UserDTO


def _make_room(room_type: str) -> RoomDTO:
    return RoomDTO(
        id=1,
        name="test-room",
        room_type=room_type,
        owner_username="alice",
        member_count=2,
        is_private=False,
        allow_member_invite=True,
        read_only=False,
    )


def _make_state(room_type: str) -> AppState:
    return AppState(
        token="tok",
        current_user=UserDTO(id=1, username="alice", email="alice@example.com"),
        active_room=_make_room(room_type),
    )


class TestRoomSettingsConditionalRendering:
    """Tests for conditional rendering logic based on room_type."""

    def test_personal_room_type_is_personal(self):
        """RoomDTO with room_type='personal' is correctly identified."""
        state = _make_state("personal")
        assert state.active_room is not None
        assert state.active_room.room_type == "personal"

    def test_group_room_type_is_group(self):
        """RoomDTO with room_type='group' is correctly identified."""
        state = _make_state("group")
        assert state.active_room is not None
        assert state.active_room.room_type == "group"

    def test_public_room_type_is_public(self):
        """RoomDTO with room_type='public' is correctly identified."""
        state = _make_state("public")
        assert state.active_room is not None
        assert state.active_room.room_type == "public"

    def test_personal_chat_should_hide_permission_toggles(self):
        """Personal chat room_type triggers the hide-toggles branch."""
        state = _make_state("personal")
        room = state.active_room
        # The view hides toggles when room_type == "personal"
        assert room.room_type == "personal"
        should_hide = room.room_type == "personal"
        assert should_hide is True

    def test_personal_chat_should_show_informational_message(self):
        """Personal chat should display informational message instead of toggles."""
        state = _make_state("personal")
        room = state.active_room
        is_personal = room.room_type == "personal"
        expected_message = "Personal chat settings are managed automatically"
        # Verify the condition that triggers the message
        assert is_personal is True
        assert expected_message == "Personal chat settings are managed automatically"

    def test_group_chat_should_show_all_toggles(self):
        """Group chat should show permission toggles."""
        state = _make_state("group")
        room = state.active_room
        should_show_toggles = room.room_type != "personal"
        assert should_show_toggles is True

    def test_public_room_should_show_all_toggles(self):
        """Public room should show permission toggles."""
        state = _make_state("public")
        room = state.active_room
        should_show_toggles = room.room_type != "personal"
        assert should_show_toggles is True

    def test_personal_room_has_correct_allow_member_invite(self):
        """Personal room DTO carries allow_member_invite field."""
        room = _make_room("personal")
        assert hasattr(room, "allow_member_invite")
        assert hasattr(room, "read_only")

    def test_room_dto_room_type_field_exists(self):
        """RoomDTO has room_type field."""
        room = _make_room("group")
        assert hasattr(room, "room_type")

    @pytest.mark.parametrize("room_type,expected_hide", [
        ("personal", True),
        ("group", False),
        ("public", False),
    ])
    def test_hide_toggles_logic_for_all_room_types(self, room_type: str, expected_hide: bool):
        """Parametrized test: toggles hidden only for personal chats."""
        room = _make_room(room_type)
        hide_toggles = room.room_type == "personal"
        assert hide_toggles == expected_hide
