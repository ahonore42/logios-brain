#!/bin/bash
# scripts/init.sh — First-time setup for Logios Brain
#
# Usage:
#   ./scripts/init.sh --email you@example.com --password your-password
#   ./scripts/init.sh --email you@example.com --password your-password --url https://your-vps.com
#
# This script:
#   1. Copies .env.example to .env if .env does not exist
#   2. Generates random secrets for SECRET_KEY, ACCESS_SECRET_KEY, POSTGRES_PASSWORD, NEO4J_PASSWORD
#      if they are not already set in .env
#   3. Starts docker compose
#   4. Waits for the app to be healthy
#   5. Runs the provisioning script to create an agent token
#
# Prerequisites: Docker, Docker Compose, git

set -euo pipefail

# ── Argument parsing ────────────────────────────────────────────────────────────

EMAIL=""
PASSWORD=""
LOGIOS_URL="http://localhost:8000"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --email)
      EMAIL="$2"; shift 2 ;;
    --password)
      PASSWORD="$2"; shift 2 ;;
    --url)
      LOGIOS_URL="$2"; shift 2 ;;
    *)
      echo "Unknown option: $1"; exit 1 ;;
  esac
done

if [[ -z "$EMAIL" ]] || [[ -z "$PASSWORD" ]]; then
  echo "Usage: $0 --email you@example.com --password your-password [--url https://your-vps.com]"
  exit 1
fi

# ── Helpers ────────────────────────────────────────────────────────────────────

log()  { echo "[init] $*"; }
bold() { echo "[init] $(printf '\033[1m%s\033[0m' "$*")"; }

die()  { echo "[init] ERROR: $*" >&2; exit 1; }

# Generate a random hex string (40 chars for SHA1-length secrets)
random_secret() {
  LC_ALL=C tr -dc 'a-f0-9' < /dev/urandom | head -c 40
}

# Check if a key is defined and non-empty in .env
env_key_set() {
  grep -q "^${1}=" .env 2>/dev/null
}

# Set a key in .env (only if not already set)
env_ensure() {
  local key="$1"
  local value="$2"
  if ! env_key_set "$key"; then
    echo "${key}=${value}" >> .env
    echo "[init]   ${key}=<generated>"
  else
    echo "[init]   ${key}=<existing>"
  fi
}

# ── Main ───────────────────────────────────────────────────────────────────────

APP_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$APP_DIR"

log "Starting Logios Brain setup..."
log "  Email:    ${EMAIL}"
log "  Logios:   ${LOGIOS_URL}"
echo

# 1. .env
log "Configuring environment..."
if [[ ! -f .env ]]; then
  cp .env.example .env
  echo "[init]   .env created from .env.example"
else
  echo "[init]   .env already exists — skipping"
fi

# 2. Generate secrets
log "Generating secrets..."
env_ensure "SECRET_KEY"         "$(random_secret)"
env_ensure "ACCESS_SECRET_KEY" "$(random_secret)"
env_ensure "POSTGRES_PASSWORD" "$(random_secret)"
env_ensure "NEO4J_PASSWORD"   "$(random_secret)"

echo

# 3. Docker compose up
log "Starting services with docker compose..."
docker compose up -d --build

echo

# 4. Wait for app health
log "Waiting for app to be healthy..."
HEALTHY=false
for i in $(seq 1 45); do
  if curl -sf "${LOGIOS_URL}/health" > /dev/null 2>&1; then
    HEALTHY=true
    break
  fi
  if [[ $i -eq 45 ]]; then
    echo
    log "App did not become healthy in time. Showing recent logs:"
    docker compose logs --tail=30
    die "Startup timed out."
  fi
  sleep 2
done

echo
log "App is healthy."

# 5. Provision agent token
echo
bold "Provisioning agent token..."
echo

SECRET_KEY=$(grep "^SECRET_KEY=" .env | cut -d= -f2)

python scripts/provision.py \
  --email    "$EMAIL" \
  --password "$PASSWORD" \
  --url      "$LOGIOS_URL" \
  --secret-key "$SECRET_KEY" \
  --save-env

echo
bold "Setup complete."
echo
echo "  Agent token saved to .env as AGENT_TOKEN and AGENT_ID."
echo
echo "  Useful commands:"
echo "    make logs    # tail service logs"
echo "    make stop    # stop all services"
echo "    make clean   # stop and remove volumes"
