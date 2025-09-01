#!/usr/bin/env bash
# One-shot setup script — run from project root to create venv, install deps,
# prepare dirs, create .env (prompt), make bootstrap executable, and optionally
# install+start a systemd service for the web UI.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")" && pwd)"
echo "Project root: $ROOT"
cd "$ROOT"

# 1) create venv
if [ ! -d ".venv" ]; then
  echo "Creating virtualenv .venv..."
  python3 -m venv .venv
fi

# activate
# shellcheck disable=SC1091
source .venv/bin/activate

# 2) install runtime deps
echo "Upgrading pip and installing dependencies..."
python -m pip install --upgrade pip >/dev/null
python -m pip install pandas requests python-dotenv openpyxl flask beautifulsoup4 lxml >/dev/null

# 3) ensure directories
mkdir -p data/jobs data/output logs data/checkpoints

# 4) create .env if missing (prompt for BRAVE_API_KEY, optional basic auth)
if [ ! -f .env ]; then
  echo ".env not found. You will be prompted for values (input hidden where indicated)."
  read -s -p "BRAVE API key (leave empty to skip): " BRAVE_KEY; echo
  read -p "Enable basic auth? [y/N]: " enable_auth
  if [ -n "$BRAVE_KEY" ]; then
    printf "BRAVE_API_KEY=%s\n" "$BRAVE_KEY" > .env
  else
    echo "BRAVE_API_KEY=REPLACE_WITH_KEY" > .env
  fi
  if [[ "$enable_auth" =~ ^[Yy] ]]; then
    read -p "BASIC_AUTH_USER: " AUTH_USER
    read -s -p "BASIC_AUTH_PASS: " AUTH_PASS; echo
    printf "BASIC_AUTH_USER=%s\nBASIC_AUTH_PASS=%s\n" "$AUTH_USER" "$AUTH_PASS" >> .env
  fi
  echo ".env created (do NOT commit this file)."
fi

# ensure .env is ignored by git
if [ -f .gitignore ]; then
  grep -qxF ".env" .gitignore || echo ".env" >> .gitignore
fi

# 5) make provided bootstrap script executable (if present)
if [ -f "scripts/bootstrap.sh" ]; then
  chmod +x scripts/bootstrap.sh
  echo "scripts/bootstrap.sh is executable."
fi

# 6) Offer to install a systemd service (Linux only)
if command -v systemctl >/dev/null 2>&1; then
  read -p "Install systemd service to run web UI on boot? [y/N]: " install_svc
  if [[ "$install_svc" =~ ^[Yy] ]]; then
    SERVICE_USER="$(whoami)"
    SERVICE_GROUP="$(id -gn "$SERVICE_USER" 2>/dev/null || echo "$SERVICE_USER")"
    SERVICE_PATH="/etc/systemd/system/openweb_enricher.service"
    echo "Will create systemd unit at $SERVICE_PATH running as $SERVICE_USER"

    sudo tee "$SERVICE_PATH" > /dev/null <<EOF
[Unit]
Description=OpenWeb Enricher web UI
After=network.target

[Service]
Type=simple
User=${SERVICE_USER}
Group=${SERVICE_GROUP}
WorkingDirectory=${ROOT}
EnvironmentFile=${ROOT}/.env
ExecStart=${ROOT}/.venv/bin/python -u -m openweb_enricher.webapp
Restart=on-failure
RestartSec=5
StandardOutput=append:/var/log/openweb_enricher.log
StandardError=inherit

[Install]
WantedBy=multi-user.target
EOF

    echo "Reloading systemd and enabling service..."
    sudo systemctl daemon-reload
    sudo systemctl enable --now openweb_enricher.service
    echo "Service installed and started. Check logs: sudo journalctl -u openweb_enricher.service -f"
  fi
else
  echo "systemd not detected — skipping service installation."
fi

# 7) final notes and quick-run helper
cat > .start-web.sh <<'SH'
#!/usr/bin/env bash
# quick helper to start webapp in foreground from project root
ROOT_DIR="$(cd "$(dirname "$0")" && pwd)"
source "$ROOT_DIR/.venv/bin/activate"
env PYTHONPATH=src python -u -m openweb_enricher.webapp
SH
chmod +x .start-web.sh

echo
echo "Setup complete."
echo " - To run in foreground: ./ .start-web.sh"
echo " - To run in background (quick): ./scripts/bootstrap.sh --daemon"
if command -v systemctl >/dev/null 2>&1; then
  echo " - If you installed the systemd service: sudo systemctl