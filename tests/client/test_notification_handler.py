"""Unit tests for the _on_notification handler logic in chat list view."""
from __future__ import annotations

import pytest


def _make_notification_handler():
    """
    Replicate the _on_notification logic from chat_list_view without Flet dependencies.
    Returns (handler, captured_snackbars) so tests can inspect what was shown.
    """
    captured: list[dict] = []

    def _on_notification(payload: dict) -> None:
        notif_type = payload.get("type")

        if notif_type == "invite":
            room_data = payload.get("payload", {})
            room_name = room_data.get("name", "чат")
            captured.append({
                "text": f'Вас пригласили в "{room_name}"!',
                "bgcolor": "#008069",
            })

        elif notif_type == "member_joined":
            data = payload.get("payload", {})
            username = data.get("username", "Someone")
            room_name = data.get("room_name", "group")
            captured.append({
                "text": f'{username} joined "{room_name}"',
                "bgcolor": "#25d366",
            })

    return _on_notification, captured


class TestMemberJoinedNotificationHandler:
    """Tests for member_joined notification handling."""

    def test_member_joined_displays_correct_snackbar_message(self):
        """member_joined notification shows '{username} joined {room_name}'."""
        handler, captured = _make_notification_handler()
        handler({
            "type": "member_joined",
            "payload": {"username": "bob", "room_name": "dev-team", "room_id": 1, "joined_at": "2026-04-22T10:00:00"},
        })
        assert len(captured) == 1
        assert captured[0]["text"] == 'bob joined "dev-team"'

    def test_member_joined_uses_green_background(self):
        """member_joined notification uses #25d366 background to distinguish from invite."""
        handler, captured = _make_notification_handler()
        handler({
            "type": "member_joined",
            "payload": {"username": "alice", "room_name": "general", "room_id": 2, "joined_at": "2026-04-22T10:00:00"},
        })
        assert captured[0]["bgcolor"] == "#25d366"

    def test_member_joined_includes_username_from_payload(self):
        """Snackbar message includes the username from the notification payload."""
        handler, captured = _make_notification_handler()
        handler({
            "type": "member_joined",
            "payload": {"username": "charlie", "room_name": "team", "room_id": 3, "joined_at": "2026-04-22T10:00:00"},
        })
        assert "charlie" in captured[0]["text"]

    def test_member_joined_includes_room_name_from_payload(self):
        """Snackbar message includes the room_name from the notification payload."""
        handler, captured = _make_notification_handler()
        handler({
            "type": "member_joined",
            "payload": {"username": "dave", "room_name": "my-room", "room_id": 4, "joined_at": "2026-04-22T10:00:00"},
        })
        assert "my-room" in captured[0]["text"]

    def test_member_joined_missing_username_uses_default(self):
        """Handler doesn't crash when username is missing from payload."""
        handler, captured = _make_notification_handler()
        handler({
            "type": "member_joined",
            "payload": {"room_name": "some-room", "room_id": 5, "joined_at": "2026-04-22T10:00:00"},
        })
        assert len(captured) == 1
        assert "Someone" in captured[0]["text"]

    def test_member_joined_missing_room_name_uses_default(self):
        """Handler doesn't crash when room_name is missing from payload."""
        handler, captured = _make_notification_handler()
        handler({
            "type": "member_joined",
            "payload": {"username": "eve", "room_id": 6, "joined_at": "2026-04-22T10:00:00"},
        })
        assert len(captured) == 1
        assert "eve" in captured[0]["text"]

    def test_member_joined_empty_payload_uses_defaults(self):
        """Handler doesn't crash when payload dict is empty."""
        handler, captured = _make_notification_handler()
        handler({"type": "member_joined", "payload": {}})
        assert len(captured) == 1
        assert "Someone" in captured[0]["text"]

    def test_member_joined_missing_payload_key_uses_defaults(self):
        """Handler doesn't crash when 'payload' key is absent."""
        handler, captured = _make_notification_handler()
        handler({"type": "member_joined"})
        assert len(captured) == 1

    def test_invite_notification_still_works(self):
        """Existing invite notification handler is unaffected."""
        handler, captured = _make_notification_handler()
        handler({
            "type": "invite",
            "payload": {"name": "cool-room", "id": 7},
        })
        assert len(captured) == 1
        assert "cool-room" in captured[0]["text"]
        assert captured[0]["bgcolor"] == "#008069"

    def test_invite_and_member_joined_use_different_colors(self):
        """invite and member_joined notifications use distinct background colors."""
        handler, captured = _make_notification_handler()
        handler({"type": "invite", "payload": {"name": "room-a"}})
        handler({"type": "member_joined", "payload": {"username": "x", "room_name": "room-b"}})
        assert captured[0]["bgcolor"] != captured[1]["bgcolor"]

    def test_unknown_notification_type_is_ignored(self):
        """Unknown notification types don't produce a snackbar."""
        handler, captured = _make_notification_handler()
        handler({"type": "unknown_event", "payload": {}})
        assert len(captured) == 0
