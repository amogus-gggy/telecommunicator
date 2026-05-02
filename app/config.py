"""Server configuration with file upload limits and other settings."""

from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

DEFAULT_CONFIG_PATH = Path("server_config.json")


@dataclass
class FileUploadLimits:
    """File upload limits configuration."""

    max_file_size_mb: int = 100  # Maximum file size in MB
    max_total_storage_mb: int = 1024  # Maximum total storage per server in MB
    allowed_extensions: list[str] = field(default_factory=lambda: [
        ".jpg", ".jpeg", ".png", ".gif", ".webp", ".svg",
        ".mp4", ".webm", ".mov", ".avi", ".mkv",
        ".mp3", ".ogg", ".wav", ".flac",
        ".pdf", ".doc", ".docx", ".xls", ".xlsx", ".ppt", ".pptx",
        ".txt", ".md", ".json", ".xml", ".csv",
        ".zip", ".rar", ".7z", ".tar", ".gz",
        ".py", ".js", ".ts", ".html", ".css", ".sql",
    ])
    blocked_extensions: list[str] = field(default_factory=lambda: [
        ".exe", ".dll", ".bat", ".cmd", ".sh", ".bin",
    ])


@dataclass
class ServerLimits:
    """Server resource limits."""

    max_users: int = 0  # 0 = unlimited
    max_rooms_per_user: int = 50
    max_members_per_room: int = 500
    max_message_length: int = 10000
    max_messages_per_room: int = 100000
    file_upload: FileUploadLimits = field(default_factory=FileUploadLimits)


@dataclass
class SecurityConfig:
    """Security-related configuration."""

    allow_registration: bool = True
    require_email_verification: bool = False
    max_login_attempts: int = 5
    lockout_duration_minutes: int = 30
    token_expire_hours: int = 24
    min_password_length: int = 8
    require_strong_password: bool = True


@dataclass
class ServerConfig:
    """Main server configuration."""

    # Server info
    server_name: str = "Telecommunicator Server"
    server_description: str = "Self-hosted secure messenger"
    
    # Feature flags
    allow_file_uploads: bool = True
    allow_voice_messages: bool = True
    allow_video_calls: bool = False  # Future feature
    enable_encryption: bool = True
    enable_backups: bool = True
    
    # Limits
    limits: ServerLimits = field(default_factory=ServerLimits)
    
    # Security
    security: SecurityConfig = field(default_factory=SecurityConfig)
    
    # Storage
    upload_dir: str = "uploads"
    max_storage_gb: float = 10.0
    
    @classmethod
    def load(cls, path: Path | str | None = None) -> "ServerConfig":
        """Load configuration from JSON file or create default."""
        config_path = Path(path) if path else DEFAULT_CONFIG_PATH
        
        if config_path.exists():
            try:
                with open(config_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                logger.info(f"[ServerConfig] Loaded from {config_path}")
                return cls._from_dict(data)
            except (json.JSONDecodeError, KeyError, TypeError) as e:
                logger.warning(f"[ServerConfig] Failed to load config: {e}, using defaults")
        else:
            logger.info(f"[ServerConfig] No config file found at {config_path}, using defaults")
        
        return cls()
    
    def save(self, path: Path | str | None = None) -> None:
        """Save configuration to JSON file."""
        config_path = Path(path) if path else DEFAULT_CONFIG_PATH
        
        try:
            with open(config_path, "w", encoding="utf-8") as f:
                json.dump(self._to_dict(), f, indent=2, ensure_ascii=False)
            logger.info(f"[ServerConfig] Saved to {config_path}")
        except Exception as e:
            logger.error(f"[ServerConfig] Failed to save config: {e}")
    
    def _to_dict(self) -> dict[str, Any]:
        """Convert config to dictionary."""
        return asdict(self)
    
    @classmethod
    def _from_dict(cls, data: dict[str, Any]) -> "ServerConfig":
        """Create config from dictionary."""
        # Parse nested dataclasses
        limits_data = data.pop("limits", {})
        security_data = data.pop("security", {})
        file_limits_data = limits_data.pop("file_upload", {})
        
        file_limits = FileUploadLimits(**file_limits_data)
        limits = ServerLimits(file_upload=file_limits, **limits_data)
        security = SecurityConfig(**security_data)
        
        return cls(limits=limits, security=security, **data)
    
    def get_max_file_size_bytes(self) -> int:
        """Get max file size in bytes."""
        return self.limits.file_upload.max_file_size_mb * 1024 * 1024
    
    def is_extension_allowed(self, filename: str) -> bool:
        """Check if file extension is allowed for upload."""
        ext = Path(filename).suffix.lower()
        
        if ext in self.limits.file_upload.blocked_extensions:
            return False
        
        if self.limits.file_upload.allowed_extensions:
            return ext in self.limits.file_upload.allowed_extensions
        
        return True


# Global config instance - initialized on import, can be reloaded
_config: ServerConfig | None = None


def get_config() -> ServerConfig:
    """Get the current server configuration."""
    global _config
    if _config is None:
        # Check for custom config path in environment
        config_path = os.getenv("SERVER_CONFIG_PATH")
        _config = ServerConfig.load(config_path)
    return _config


def reload_config(path: Path | str | None = None) -> ServerConfig:
    """Reload configuration from file."""
    global _config
    config_path = path or os.getenv("SERVER_CONFIG_PATH")
    _config = ServerConfig.load(config_path)
    return _config
