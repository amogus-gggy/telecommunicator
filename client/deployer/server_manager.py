"""Server deployment and management logic."""

from __future__ import annotations

import json
import logging
import os
import tempfile
import zipfile
from pathlib import Path
from typing import Callable

from .ssh_client import SSHClient, SSHCredentials, DeploymentError

logger = logging.getLogger(__name__)

# Installation script template
INSTALL_SCRIPT = '''#!/bin/bash
set -e

echo "=== Telecommunicator Server Installer ==="

# Configuration
INSTALL_DIR="{install_dir}"
SERVER_PORT={port}
PYTHON_VERSION="3.11"

# Colors
RED='\\033[0;31m'
GREEN='\\033[0;32m'
NC='\\033[0m'

export DEBIAN_FRONTEND=noninteractive

echo "[1/8] Updating system packages..."
apt-get update

echo "[2/8] Installing dependencies..."
apt-get install -y -o Dpkg::Options::="--force-confdef" -o Dpkg::Options::="--force-confold" python3 python3-pip python3-venv git sqlite3 curl unzip

echo "[3/8] Creating install directory..."
mkdir -p "$INSTALL_DIR"
cd "$INSTALL_DIR"

echo "[4/8] Extracting server files..."
if [ -f /tmp/telecommunicator_server.zip ]; then
    unzip -o /tmp/telecommunicator_server.zip -d "$INSTALL_DIR"
    rm /tmp/telecommunicator_server.zip
fi

echo "[5/8] Setting up Python environment..."
python3 -m venv venv
source venv/bin/activate
pip install --quiet --upgrade pip
pip install --quiet -r requirements.txt

echo "[6/8] Creating config..."
cd "$INSTALL_DIR"

# Create default config
if [ ! -f server_config.json ] || [ "{force_reinstall}" = "true" ]; then
cat > server_config.json << 'EOFCFG'
{{
  "server_name": "Telecommunicator Server",
  "server_description": "Self-hosted secure messenger",
  "allow_file_uploads": true,
  "allow_voice_messages": true,
  "enable_encryption": true,
  "enable_backups": true,
  "upload_dir": "uploads",
  "max_storage_gb": 10,
  "limits": {{
    "max_file_size_mb": {max_file_size_mb},
    "max_rooms_per_user": 50,
    "max_members_per_room": 500,
    "max_message_length": 10000
  }}
}}
EOFCFG
fi

# Note: Database migrations run automatically on server startup

echo "[7/8] Initializing directories..."
mkdir -p "$INSTALL_DIR/uploads"
mkdir -p "$INSTALL_DIR/logs"
mkdir -p "$INSTALL_DIR/alembic/versions"

echo "[8/8] Creating systemd service..."
cat > /etc/systemd/system/telecommunicator.service << 'EOF'
[Unit]
Description=Telecommunicator Server
After=network.target

[Service]
Type=simple
User=root
WorkingDirectory={install_dir}
Environment="PATH={install_dir}/venv/bin"
Environment="SERVER_CONFIG_PATH={install_dir}/server_config.json"
ExecStart={install_dir}/venv/bin/python run_server.py --host 0.0.0.0 --port {port}
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
systemctl enable telecommunicator.service

echo -e "${{GREEN}}=== Installation complete! ===${{NC}}"
echo "Server installed at: $INSTALL_DIR"
echo "Config file: {install_dir}/server_config.json"
echo "Service: telecommunicator"
echo ""
echo "Commands:"
echo "  systemctl start telecommunicator   - Start server"
echo "  systemctl stop telecommunicator    - Stop server"
echo "  systemctl status telecommunicator  - Check status"
echo ""
echo "API available at: http://$(curl -s ifconfig.me):{port}"
'''


class ServerManager:
    """Manages remote server deployment and lifecycle."""

    DEFAULT_INSTALL_DIR = "/opt/telecommunicator"
    DEFAULT_PORT = 8000

    def __init__(self, creds: SSHCredentials) -> None:
        self.creds = creds
        self._ssh: SSHClient | None = None

    def connect(self) -> None:
        """Connect to remote server."""
        self._ssh = SSHClient(self.creds)
        self._ssh.connect()

    def disconnect(self) -> None:
        """Disconnect from remote server."""
        if self._ssh:
            self._ssh.disconnect()
            self._ssh = None

    def check_server_status(self) -> dict:
        """Check if server is installed and running."""
        if not self._ssh:
            raise DeploymentError("Not connected")

        result = {
            "installed": False,
            "running": False,
            "version": None,
            "port": None,
        }

        # Check if installed
        exit_code, _, _ = self._ssh.exec_command(
            f"test -d {self.DEFAULT_INSTALL_DIR}"
        )
        result["installed"] = exit_code == 0

        # Check if service is running
        exit_code, stdout, _ = self._ssh.exec_command(
            "systemctl is-active telecommunicator"
        )
        result["running"] = "active" in stdout

        # Get port from config
        exit_code, stdout, _ = self._ssh.exec_command(
            f"cat {self.DEFAULT_INSTALL_DIR}/server_config.json 2>/dev/null || echo '{{}}'"
        )
        try:
            config = json.loads(stdout)
            result["port"] = config.get("port", self.DEFAULT_PORT)
        except json.JSONDecodeError:
            pass

        return result

    def deploy(
        self,
        local_project_path: str | None = None,
        install_dir: str | None = None,
        port: int = DEFAULT_PORT,
        config: dict | None = None,
        progress_callback: Callable[[str], None] | None = None,
        force_reinstall: bool = False,
    ) -> bool:
        """Deploy server to remote host.

        Args:
            local_project_path: Path to local server code (None = use current project)
            install_dir: Remote installation directory
            port: Server port
            config: Server configuration dict
            progress_callback: Progress callback function
            force_reinstall: If True, remove existing installation first

        Returns:
            True if deployment successful
        """
        # Remove existing installation if force_reinstall
        if force_reinstall and self._ssh:
            if progress_callback:
                progress_callback("Removing existing installation...")
            self._ssh.exec_command(f"rm -rf {install_dir or self.DEFAULT_INSTALL_DIR}", sudo=True)
        if not self._ssh:
            raise DeploymentError("Not connected")

        install_dir = install_dir or self.DEFAULT_INSTALL_DIR

        try:
            # Step 1: Create and upload server package
            if progress_callback:
                progress_callback("Creating server package...")

            project_path = local_project_path or self._find_project_root()
            zip_path = self._create_server_package(project_path, config)

            # Step 2: Upload package
            if progress_callback:
                progress_callback("Uploading to server...")

            self._ssh.upload_file(zip_path, "/tmp/telecommunicator_server.zip")

            # Cleanup temp file
            os.unlink(zip_path)

            # Step 3: Create and run install script
            if progress_callback:
                progress_callback("Running installation...")

            max_file_size_mb = config.get("limits", {}).get("file_upload", {}).get("max_file_size_mb", 100) if config else 100
            install_script = INSTALL_SCRIPT.format(
                install_dir=install_dir,
                port=port,
                max_file_size_mb=max_file_size_mb,
                force_reinstall=str(force_reinstall).lower(),
            )

            self._ssh.upload_string(
                install_script, "/tmp/install_telecommunicator.sh", mode=0o755
            )

            exit_code, stdout, stderr = self._ssh.exec_command(
                "bash /tmp/install_telecommunicator.sh",
                sudo=True,
                timeout=600,
                progress_callback=progress_callback,
            )

            if exit_code != 0:
                raise DeploymentError(
                    f"Installation failed: {stderr[:500]}"
                )

            # Step 4: Start service
            if progress_callback:
                progress_callback("Starting server...")

            exit_code, _, _ = self._ssh.exec_command(
                "systemctl start telecommunicator", sudo=True
            )

            if progress_callback:
                progress_callback("Deployment complete!")

            return True

        except Exception as e:
            logger.exception("[ServerManager] Deployment failed")
            raise DeploymentError(f"Deployment failed: {e}")

    def start_server(self) -> bool:
        """Start the server service."""
        if not self._ssh:
            raise DeploymentError("Not connected")

        exit_code, _, _ = self._ssh.exec_command(
            "systemctl start telecommunicator", sudo=True
        )
        return exit_code == 0

    def stop_server(self) -> bool:
        """Stop the server service."""
        if not self._ssh:
            raise DeploymentError("Not connected")

        exit_code, _, _ = self._ssh.exec_command(
            "systemctl stop telecommunicator", sudo=True
        )
        return exit_code == 0

    def restart_server(self) -> bool:
        """Restart the server service."""
        if not self._ssh:
            raise DeploymentError("Not connected")

        exit_code, _, _ = self._ssh.exec_command(
            "systemctl restart telecommunicator", sudo=True
        )
        return exit_code == 0

    def get_logs(self, lines: int = 50) -> str:
        """Get server logs."""
        if not self._ssh:
            raise DeploymentError("Not connected")

        exit_code, stdout, _ = self._ssh.exec_command(
            f"journalctl -u telecommunicator -n {lines} --no-pager"
        )
        return stdout if exit_code == 0 else ""

    def update_config(self, config: dict) -> bool:
        """Update server configuration."""
        if not self._ssh:
            raise DeploymentError("Not connected")

        config_path = f"{self.DEFAULT_INSTALL_DIR}/server_config.json"
        config_json = json.dumps(config, indent=2, ensure_ascii=False)

        self._ssh.upload_string(config_json, config_path)

        # Restart to apply changes
        return self.restart_server()

    def _find_project_root(self) -> str:
        """Find the project root directory."""
        # Start from current file location
        current = Path(__file__).resolve().parent

        # Go up until we find app/main.py or similar
        while current != current.parent:
            if (current / "app" / "main.py").exists():
                return str(current)
            if (current / "requirements.txt").exists() and (
                current / "run_server.py"
            ).exists():
                return str(current)
            current = current.parent

        raise DeploymentError(
            "Could not find project root. Please specify local_project_path."
        )

    def _create_server_package(
        self, project_path: str, config: dict | None = None
    ) -> str:
        """Create a zip package of the server."""
        # Create temp file
        fd, zip_path = tempfile.mkstemp(suffix=".zip")
        os.close(fd)

        project = Path(project_path)

        with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
            # Add Python files and config
            for pattern in ["app/**/*.py", "*.py", "*.txt", "*.json", "*.ini"]:
                for file_path in project.glob(pattern):
                    if "__pycache__" in str(file_path):
                        continue
                    arc_name = file_path.relative_to(project)
                    zf.write(file_path, arc_name)

            # Add alembic directory (env.py, script.py.mako, versions/)
            alembic_dir = project / "alembic"
            if alembic_dir.exists():
                for file_path in alembic_dir.rglob("*"):
                    if "__pycache__" in str(file_path) or file_path.is_dir():
                        continue
                    arc_name = file_path.relative_to(project)
                    zf.write(file_path, arc_name)

            # Add config if provided
            if config:
                config_json = json.dumps(config, indent=2, ensure_ascii=False)
                zf.writestr("server_config.json", config_json)

        return zip_path

    def __enter__(self) -> "ServerManager":
        self.connect()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        self.disconnect()
