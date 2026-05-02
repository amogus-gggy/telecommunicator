"""Server info and configuration endpoints."""

from __future__ import annotations

from fastapi import APIRouter

from app.config import get_config

router = APIRouter(prefix="/server", tags=["server"])


@router.get("/info")
async def get_server_info():
    """Get public server information and feature flags."""
    config = get_config()
    return {
        "server_name": config.server_name,
        "server_description": config.server_description,
        "features": {
            "allow_file_uploads": config.allow_file_uploads,
            "allow_voice_messages": config.allow_voice_messages,
            "allow_video_calls": config.allow_video_calls,
            "enable_encryption": config.enable_encryption,
            "enable_backups": config.enable_backups,
            "allow_registration": config.security.allow_registration,
            "require_email_verification": config.security.require_email_verification,
        },
        "limits": {
            "max_file_size_mb": config.limits.file_upload.max_file_size_mb,
            "max_rooms_per_user": config.limits.max_rooms_per_user,
            "max_members_per_room": config.limits.max_members_per_room,
            "max_message_length": config.limits.max_message_length,
            "max_users": config.limits.max_users,
        },
    }


@router.get("/limits")
async def get_server_limits():
    """Get server limits (convenience endpoint)."""
    config = get_config()
    return {
        "max_file_size_mb": config.limits.file_upload.max_file_size_mb,
        "max_total_storage_mb": config.limits.file_upload.max_total_storage_mb,
        "allowed_extensions": config.limits.file_upload.allowed_extensions,
        "blocked_extensions": config.limits.file_upload.blocked_extensions,
        "max_rooms_per_user": config.limits.max_rooms_per_user,
        "max_members_per_room": config.limits.max_members_per_room,
        "max_message_length": config.limits.max_message_length,
        "max_messages_per_room": config.limits.max_messages_per_room,
    }
