#!/bin/bash
# deploy.sh — Deploy Logios Brain to a VPS or cloud server
#
# Usage:
#   ./scripts/deploy.sh <server_ip> <ssh_user>
#
# Or set environment variables:
#   export SERVER_IP=your.vps.ip
#   export SSH_USER=your_user
#   ./scripts/deploy.sh
#
# Prerequisites on the server:
#   - SSH key-based access
#   - Docker and Docker Compose installed
#   - Repository cloned to ~/logios-brain
#   - .env file present at ~/logios-brain/.env with all credentials

set -euo pipefail

SERVER_IP="${1:-$SERVER_IP}"
SSH_USER="${2:-$SSH_USER}"

if [[ -z "$SERVER_IP" ]] || [[ -z "$SSH_USER" ]]; then
  echo "Usage: $0 <server_ip> <ssh_user>"
  echo "   or: SERVER_IP=... SSH_USER=... $0"
  exit 1
fi

echo "==> Deploying Logios Brain to $SERVER_IP..."

ssh "$SSH_USER@$SERVER_IP" << 'ENDSSH'
  set -euo pipefail
  APP_DIR="$HOME/logios-brain"

  echo "==> Pulling latest code..."
  cd "$APP_DIR"
  git fetch origin main
  git checkout main
  git pull

  echo "==> Building and starting containers..."
  docker compose up -d --build

  echo "==> Waiting for app to be healthy..."
  for i in $(seq 1 30); do
    if curl -sf http://localhost:8000/health > /dev/null 2>&1; then
      echo "App is healthy."
      break
    fi
    if [[ $i -eq 30 ]]; then
      echo "ERROR: App did not become healthy in time."
      docker compose logs --tail=50
      exit 1
    fi
    sleep 2
  done

  echo "==> Deploy complete."
ENDSSH

echo "Done."
