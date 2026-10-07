#!/usr/bin/env bash
# One-shot Telecommunicator server deployment for a fresh Ubuntu/Debian VPS.
set -euo pipefail

echo "[1/4] Checking docker..."
if ! command -v docker >/dev/null 2>&1; then
  apt-get update && apt-get install -y curl
  curl -fsSL https://get.docker.com | sh
fi

echo "[2/4] Configuration..."
SECRET=${SECRET_KEY:-$(head -c 32 /dev/urandom | od -An -tx1 | tr -d ' \n')}
ADDR=${SERVER_ADDRESS:-$(hostname -I | awk '{print $1}'):8000}

echo "[3/4] Pulling and starting the container..."
docker rm -f telecommunicator >/dev/null 2>&1 || true
docker pull ghcr.io/amogus-gggy/telecommunicator:latest
docker run -d --name telecommunicator --restart unless-stopped \
  -p 8000:8000 \
  -e SECRET_KEY="${SECRET}" \
  -e SERVER_ADDRESS="${ADDR}" \
  -e DATABASE_URL="sqlite+aiosqlite:////data/messenger.db" \
  -v td_data:/data \
  -v td_uploads:/app/uploads \
  ghcr.io/amogus-gggy/telecommunicator:latest

echo "[4/4] Telecommunicator is running on port 8000"
