#!/usr/bin/env bash
set -euo pipefail

SERVICE_NAME="${GUNICORN_SERVICE:-gunicorn}"
LINES="${LINES:-100}"

if ! command -v journalctl >/dev/null 2>&1; then
  echo "journalctl not available on this system." >&2
  exit 1
fi

exec sudo journalctl -u "$SERVICE_NAME" -f -n "$LINES"
