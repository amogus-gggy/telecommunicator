"""SSH client for remote server deployment."""

from __future__ import annotations

import io
import logging
import os
import tarfile
from dataclasses import dataclass
from typing import Callable

import paramiko

logger = logging.getLogger(__name__)


class DeploymentError(Exception):
    """Error during server deployment."""

    pass


@dataclass
class SSHCredentials:
    """SSH connection credentials."""

    host: str
    username: str
    password: str | None = None
    private_key: str | None = None  # Path to private key or key content
    port: int = 22


class SSHClient:
    """SSH client for remote server operations."""

    def __init__(self, creds: SSHCredentials) -> None:
        self.creds = creds
        self._client: paramiko.SSHClient | None = None
        self._sftp: paramiko.SFTPClient | None = None

    def connect(self) -> None:
        """Establish SSH connection."""
        try:
            self._client = paramiko.SSHClient()
            self._client.set_missing_host_key_policy(paramiko.AutoAddPolicy())

            connect_kwargs: dict = {
                "hostname": self.creds.host,
                "port": self.creds.port,
                "username": self.creds.username,
                "timeout": 30,
            }

            if self.creds.private_key:
                # Check if it's a path or key content
                if os.path.exists(self.creds.private_key):
                    connect_kwargs["key_filename"] = self.creds.private_key
                else:
                    # Load key from string
                    key_file = io.StringIO(self.creds.private_key)
                    private_key = paramiko.RSAKey.from_private_key(key_file)
                    connect_kwargs["pkey"] = private_key
            elif self.creds.password:
                connect_kwargs["password"] = self.creds.password
            else:
                raise DeploymentError("Either password or private_key required")

            self._client.connect(**connect_kwargs)
            self._sftp = self._client.open_sftp()
            logger.info(f"[SSH] Connected to {self.creds.host}:{self.creds.port}")

        except paramiko.AuthenticationException as e:
            raise DeploymentError(f"Authentication failed: {e}")
        except paramiko.SSHException as e:
            raise DeploymentError(f"SSH connection failed: {e}")
        except Exception as e:
            raise DeploymentError(f"Connection error: {e}")

    def disconnect(self) -> None:
        """Close SSH connection."""
        if self._sftp:
            try:
                self._sftp.close()
            except Exception:
                pass
            self._sftp = None

        if self._client:
            try:
                self._client.close()
            except Exception:
                pass
            self._client = None

        logger.info("[SSH] Disconnected")

    def exec_command(
        self,
        command: str,
        sudo: bool = False,
        timeout: int = 300,
        progress_callback: Callable[[str], None] | None = None,
    ) -> tuple[int, str, str]:
        """Execute command on remote server.

        Returns: (exit_code, stdout, stderr)
        """
        if not self._client:
            raise DeploymentError("Not connected")

        if sudo and self.creds.password:
            # Use sudo with password
            command = f'echo "{self.creds.password}" | sudo -S bash -c \'{command}\''

        logger.info(f"[SSH] Executing: {command[:50]}...")
        if progress_callback:
            progress_callback(f"$ {command[:60]}...")

        stdin, stdout, stderr = self._client.exec_command(command, timeout=timeout)

        # Read output
        stdout_data = stdout.read().decode("utf-8", errors="replace")
        stderr_data = stderr.read().decode("utf-8", errors="replace")
        exit_code = stdout.channel.recv_exit_status()

        # Stream output for progress
        if progress_callback:
            for line in stdout_data.splitlines():
                progress_callback(f"> {line}")
            for line in stderr_data.splitlines():
                progress_callback(f"! {line}")

        return exit_code, stdout_data, stderr_data

    def upload_file(
        self,
        local_path: str,
        remote_path: str,
        progress_callback: Callable[[str], None] | None = None,
    ) -> None:
        """Upload file to remote server."""
        if not self._sftp:
            raise DeploymentError("Not connected")

        logger.info(f"[SSH] Uploading {local_path} -> {remote_path}")
        if progress_callback:
            progress_callback(f"Uploading {os.path.basename(local_path)}...")

        self._sftp.put(local_path, remote_path)

    def upload_string(
        self,
        content: str,
        remote_path: str,
        mode: int = 0o644,
    ) -> None:
        """Upload string content as file."""
        if not self._sftp:
            raise DeploymentError("Not connected")

        with self._sftp.file(remote_path, "w") as f:
            f.write(content)
        self._sftp.chmod(remote_path, mode)

    def download_file(self, remote_path: str, local_path: str) -> None:
        """Download file from remote server."""
        if not self._sftp:
            raise DeploymentError("Not connected")

        self._sftp.get(remote_path, local_path)

    def file_exists(self, remote_path: str) -> bool:
        """Check if file exists on remote server."""
        if not self._sftp:
            raise DeploymentError("Not connected")

        try:
            self._sftp.stat(remote_path)
            return True
        except FileNotFoundError:
            return False

    def mkdir(self, remote_path: str, mode: int = 0o755) -> None:
        """Create directory on remote server."""
        if not self._sftp:
            raise DeploymentError("Not connected")

        try:
            self._sftp.mkdir(remote_path)
            self._sftp.chmod(remote_path, mode)
        except IOError:
            # Directory might already exist
            pass

    def __enter__(self) -> "SSHClient":
        self.connect()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        self.disconnect()
