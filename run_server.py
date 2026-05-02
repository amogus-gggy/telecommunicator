#!/usr/bin/env python3
"""
Telecommunicator Server Launcher

Usage:
    python run_server.py              # Run with default config
    python run_server.py --config custom_config.json
    python run_server.py --host 0.0.0.0 --port 8080

Environment variables:
    SERVER_CONFIG_PATH - Path to config file
    SECRET_KEY - JWT signing key (required for production)
    ACCESS_TOKEN_EXPIRE_HOURS - Token expiration time
    DATABASE_URL - Database connection URL
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

# Resolve the directory where this script lives and add it to sys.path
# so the app module is importable regardless of cwd
_SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(_SCRIPT_DIR))

# Also chdir to the script directory so relative paths (config, db, uploads) work
os.chdir(_SCRIPT_DIR)

import uvicorn
from app.config import get_config, reload_config


def create_default_config() -> None:
    """Create default config file if it doesn't exist."""
    config_path = Path("server_config.json")
    if not config_path.exists():
        example_path = Path("server_config.example.json")
        if example_path.exists():
            import shutil
            shutil.copy(example_path, config_path)
            print(f"[Server] Created default config: {config_path}")
        else:
            # Create minimal config
            config = get_config()
            config.save(config_path)
            print(f"[Server] Created minimal config: {config_path}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Telecommunicator Server")
    parser.add_argument(
        "--config", "-c",
        help="Path to server configuration file",
        default=os.getenv("SERVER_CONFIG_PATH", "server_config.json")
    )
    parser.add_argument(
        "--host", "-H",
        help="Host to bind to",
        default="0.0.0.0"
    )
    parser.add_argument(
        "--port", "-p",
        help="Port to bind to",
        type=int,
        default=8000
    )
    parser.add_argument(
        "--reload",
        help="Enable auto-reload for development",
        action="store_true"
    )
    parser.add_argument(
        "--init-config",
        help="Create default config file and exit",
        action="store_true"
    )
    parser.add_argument(
        "--show-config",
        help="Show current config and exit",
        action="store_true"
    )

    args = parser.parse_args()

    if args.init_config:
        create_default_config()
        return

    # Set config path (resolve relative to script dir)
    config_path = Path(args.config)
    if not config_path.is_absolute():
        config_path = _SCRIPT_DIR / config_path
    os.environ["SERVER_CONFIG_PATH"] = str(config_path)

    # Ensure config file exists
    if not config_path.exists():
        print(f"[Server] Config file not found: {config_path}")
        print("[Server] Creating default configuration...")
        config = get_config()
        config.save(config_path)

    # Load and display config
    reload_config(str(config_path))
    config = get_config()

    print(f"[Server] {config.server_name}")
    print(f"[Server] Description: {config.server_description}")
    print(f"[Server] File uploads: {'enabled' if config.allow_file_uploads else 'disabled'}")
    print(f"[Server] Max file size: {config.limits.file_upload.max_file_size_mb} MB")
    print(f"[Server] Max storage: {config.max_storage_gb} GB")
    print(f"[Server] Registration: {'open' if config.security.allow_registration else 'closed'}")

    if args.show_config:
        import json
        print("\n[Server] Full configuration:")
        print(json.dumps(config._to_dict(), indent=2, ensure_ascii=False))
        return

    # Run server
    print(f"\n[Server] Starting on http://{args.host}:{args.port}")
    print("[Server] Press Ctrl+C to stop\n")

    uvicorn.run(
        "app.main:app",
        host=args.host,
        port=args.port,
        reload=args.reload,
        log_level="info",
        reload_dirs=[str(_SCRIPT_DIR)] if args.reload else None,
    )


if __name__ == "__main__":
    main()
