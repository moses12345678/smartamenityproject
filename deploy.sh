#!/usr/bin/env bash
set -euo pipefail

# Directory of this script (project root with manage.py)
PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$PROJECT_DIR"

SERVICE_NAME="${GUNICORN_SERVICE:-gunicorn}"
NGINX_SERVICE="${NGINX_SERVICE:-nginx}"
PYTHON_BIN="${PYTHON_BIN:-python3}"

# Resolve virtualenv: prefer user-specified; else auto-detect ../venv then ./venv
if [ -n "${VENV_DIR:-}" ]; then
  VENV_DIR="${VENV_DIR}"
elif [ -d "${PROJECT_DIR}/../venv" ]; then
  VENV_DIR="${PROJECT_DIR}/../venv"
elif [ -d "${PROJECT_DIR}/venv" ]; then
  VENV_DIR="${PROJECT_DIR}/venv"
else
  echo "Error: virtualenv not found. Set VENV_DIR or create ./venv or ../venv."
  exit 1
fi

echo "Using project dir: $PROJECT_DIR"
echo "Virtualenv: $VENV_DIR"
echo "Gunicorn service: $SERVICE_NAME"
echo "Nginx service: $NGINX_SERVICE"

# Virtualenv already expected to exist; uncomment if you ever need auto-create
# if [ ! -d "$VENV_DIR" ]; then
#   echo "Creating virtualenv..."
#   "$PYTHON_BIN" -m venv "$VENV_DIR"
# fi

source "$VENV_DIR/bin/activate"
echo "[1/3] Upgrading pip..."
python -m pip install --upgrade pip >/tmp/deploy_pip.log && echo "pip upgrade: OK" || { echo "pip upgrade FAILED"; cat /tmp/deploy_pip.log; exit 1; }
echo "[2/3] Installing requirements..."
python -m pip install -r requirements.txt >/tmp/deploy_requirements.log && echo "requirements install: OK" || { echo "requirements install FAILED"; cat /tmp/deploy_requirements.log; exit 1; }

# Run migrations/static as part of deploy
echo "[3/3] Applying migrations..."
python manage.py migrate --noinput >/tmp/deploy_migrate.log && echo "migrate: OK" || { echo "migrate FAILED"; cat /tmp/deploy_migrate.log; exit 1; }
echo "[extra] collectstatic..."
python manage.py collectstatic --noinput >/tmp/deploy_collectstatic.log && echo "collectstatic: OK" || { echo "collectstatic FAILED"; cat /tmp/deploy_collectstatic.log; exit 1; }

if command -v systemctl >/dev/null 2>&1; then
  echo "Restarting $SERVICE_NAME via systemctl..."
  sudo systemctl restart "$SERVICE_NAME"
  sudo systemctl status "$SERVICE_NAME" --no-pager

  echo "Restarting $NGINX_SERVICE via systemctl..."
  sudo systemctl restart "$NGINX_SERVICE"
  sudo systemctl status "$NGINX_SERVICE" --no-pager
else
  echo "systemctl not found; start gunicorn manually if needed."
fi

echo "Deploy completed successfully."
