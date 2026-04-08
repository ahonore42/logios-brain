#!/bin/bash
# deploy.sh — Deploy Logios Brain to Hetzner VPS
#
# Usage:
#   ./scripts/deploy.sh <hetzner_ip> <ssh_user>
#
# Or set environment variables:
#   export HETZNER_IP=your.vps.ip
#   export HETZNER_USER=your_user
#   ./scripts/deploy.sh
#
# Prerequisites:
#   - SSH key-based access to Hetzner VPS
#   - Repository pushed to GitHub (deploy fetches from git)
#   - /home/$USER/logios-brain directory exists on VPS (cloned from git)
#   - .env file present at $HOME/logios-brain/.env
#   - Docker and docker compose installed on VPS
#   - Schema migrations applied: psql -f $HOME/logios-brain/schema/migrations/*.sql
#   - Python 3.11 venv created at $HOME/logios-brain/server/venv

set -euo pipefail

HETZNER_IP="${1:-$HETZNER_IP}"
SSH_USER="${2:-$HETZNER_USER}"

if [[ -z "$HETZNER_IP" ]] || [[ -z "$SSH_USER" ]]; then
  echo "Usage: $0 <hetzner_ip> <ssh_user>"
  echo "   or: HETZNER_IP=... HETZNER_USER=... $0"
  exit 1
fi

echo "==> Deploying Logios Brain to Hetzner ($HETZNER_IP)..."

ssh "$SSH_USER@$HETZNER_IP" << 'ENDSSH'
  set -euo pipefail
  APP_DIR="$HOME/logios-brain"
  VENV_DIR="$APP_DIR/venv"

  echo "==> Pulling latest code..."
  cd "$APP_DIR"
  git checkout main
  git pull

  echo "==> Pulling Docker images..."
  docker compose pull

  echo "==> Starting containers..."
  docker compose up -d

  echo "==> Waiting for PostgreSQL to be healthy..."
  for i in $(seq 1 30); do
    if docker compose exec -T postgres pg_isready -U logios -d logios_brain > /dev/null 2>&1; then
      echo "PostgreSQL is healthy."
      break
    fi
    if [[ $i -eq 30 ]]; then
      echo "ERROR: PostgreSQL did not become healthy in time."
      exit 1
    fi
    sleep 2
  done

  echo "==> Restarting FastAPI server..."
  sudo systemctl restart logios-brain

  echo "==> Verifying server is up..."
  sleep 3
  if curl -sf http://localhost:8000/health > /dev/null; then
    echo "FastAPI server is up."
  else
    echo "ERROR: FastAPI server health check failed."
    journalctl -u logios-brain --no-pager -n 20
    exit 1
  fi

  echo "==> Running connection test..."
  if command -v python3 &> /dev/null && [[ -f "$APP_DIR/scripts/test_connection.py" ]]; then
    source "$VENV_DIR/bin/activate" 2>/dev/null || true
    python3 "$APP_DIR/scripts/test_connection.py" || true
  fi

  echo "==> Deploy complete."
ENDSSH

echo "Done."