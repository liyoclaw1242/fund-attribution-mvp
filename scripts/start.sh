#!/usr/bin/env bash
# One-click startup helper for the Fund Attribution MVP stack.
#
# Usage:
#   scripts/start.sh              # dev stack (db + pipeline + service + app)
#   scripts/start.sh production   # dev stack + nginx reverse proxy on :80/:443

set -euo pipefail

cd "$(dirname "$0")/.."

if [ ! -f .env ]; then
    cp .env.example .env
    echo "Created .env from .env.example"
    echo "Edit it with your ANTHROPIC_API_KEY and any other secrets, then re-run this script."
    exit 0
fi

if ! grep -q "^ANTHROPIC_API_KEY=sk-" .env; then
    echo "WARN: ANTHROPIC_API_KEY in .env does not look set. AI summaries will fall back to template mode."
fi

PROFILE_ARGS=()
if [ "${1:-}" = "production" ]; then
    PROFILE_ARGS=(--profile production)
    echo "Starting stack WITH nginx reverse proxy (production profile)..."
else
    echo "Starting dev stack (no nginx). Use 'scripts/start.sh production' to include nginx."
fi

docker compose "${PROFILE_ARGS[@]}" up -d

echo
echo "Waiting for services to become healthy..."
docker compose "${PROFILE_ARGS[@]}" ps

echo
echo "Ready:"
echo "  Streamlit UI:  http://localhost:8501"
echo "  FastAPI docs:  http://localhost:8000/docs"
if [ "${1:-}" = "production" ]; then
    echo "  Nginx proxy:   http://localhost/ (UI) and http://localhost/api/ (API)"
fi
