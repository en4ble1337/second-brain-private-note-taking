#!/usr/bin/env bash
# Install script — run once on the host machine after cloning the repo.
# Idempotent: safe to run multiple times.
#
# Usage:
#   cd <install-path>
#   sudo bash deployment/install.sh
#
# Assumptions:
#   - Ubuntu 24.04 / Debian Bookworm (or compatible Debian-based distro)
#   - Python 3.11+ available
#   - Ollama already installed (curl -fsSL https://ollama.com/install.sh | sh)
#   - Run with sudo (SUDO_USER is used to detect the actual install user)

set -euo pipefail

INSTALL_USER="${SUDO_USER:-$(logname 2>/dev/null || whoami)}"
INSTALL_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
VENV_DIR="$INSTALL_DIR/.venv"

echo "=== Second Brain Installer ==="
echo "Install dir : $INSTALL_DIR"
echo "Install user: $INSTALL_USER"
echo ""

# ── 1. System packages ──────────────────────────────────────────────────────
echo "[1/8] Installing system packages..."
sudo apt-get update -qq
sudo apt-get install -y -qq \
    python3-pip \
    python3-venv \
    authbind \
    avahi-daemon \
    avahi-utils \
    libavahi-compat-libdnssd-dev

# ── 2. Hostname (mybrain.local) ──────────────────────────────────────────────
echo "[2/8] Setting hostname to 'mybrain'..."
CURRENT_HOSTNAME=$(hostname)
if [ "$CURRENT_HOSTNAME" != "mybrain" ]; then
    sudo hostnamectl set-hostname mybrain
    sudo sed -i "s/$CURRENT_HOSTNAME/mybrain/g" /etc/hosts
    echo "  Hostname changed: $CURRENT_HOSTNAME → mybrain"
else
    echo "  Hostname already 'mybrain', skipping."
fi

# ── 3. Python virtual environment ───────────────────────────────────────────
echo "[3/8] Creating Python virtual environment..."
if [ ! -d "$VENV_DIR" ]; then
    python3 -m venv "$VENV_DIR"
fi
"$VENV_DIR/bin/pip" install --upgrade pip -q
"$VENV_DIR/bin/pip" install -r "$INSTALL_DIR/requirements.txt" -q
echo "  Dependencies installed."

# ── 4. Production .env ──────────────────────────────────────────────────────
echo "[4/8] Configuring .env..."
ENV_FILE="$INSTALL_DIR/.env"
if [ ! -f "$ENV_FILE" ]; then
    TOKEN=$(python3 -c "import secrets; print(secrets.token_hex(32))")
    SECRET=$(python3 -c "import secrets; print(secrets.token_hex(32))")
    cat > "$ENV_FILE" <<EOF
INGEST_TOKEN=$TOKEN
SECRET_KEY=$SECRET
DATA_DIR=$INSTALL_DIR/data
OLLAMA_BASE_URL=http://127.0.0.1:11434
OLLAMA_MODEL=llama3.2:3b
WHISPER_MODEL=base
MAX_AUDIO_SIZE_MB=500
WORKER_POLL_INTERVAL=2
HOST=0.0.0.0
PORT=80
EOF
    chmod 600 "$ENV_FILE"
    echo "  .env created with fresh secrets."
    echo ""
    echo "  *** IMPORTANT: Save your ingest token from .env — you will need it"
    echo "  *** for the iOS Shortcut. View it with: cat $ENV_FILE | grep INGEST_TOKEN"
    echo ""
else
    echo "  .env already exists, skipping. Delete it to regenerate secrets."
fi

# Create data directories
mkdir -p "$INSTALL_DIR/data/raw" "$INSTALL_DIR/data/db"

# ── 5. authbind for port 80 ──────────────────────────────────────────────────
echo "[5/8] Configuring authbind for port 80..."
sudo touch /etc/authbind/byport/80
sudo chmod 500 /etc/authbind/byport/80
sudo chown "$INSTALL_USER" /etc/authbind/byport/80
echo "  authbind configured."

# ── 6. Ollama: localhost-only binding + model pull ───────────────────────────
echo "[6/8] Configuring Ollama..."
sudo mkdir -p /etc/systemd/system/ollama.service.d
sudo cp "$INSTALL_DIR/deployment/ollama-override.conf" \
    /etc/systemd/system/ollama.service.d/override.conf
sudo systemctl daemon-reload
sudo systemctl enable ollama
sudo systemctl restart ollama
echo "  Waiting for Ollama to start..."
sleep 3
echo "  Pulling llama3.2:3b model (this may take several minutes on first run)..."
ollama pull llama3.2:3b
echo "  Ollama ready."

# ── 7. Avahi mDNS service advertisement ─────────────────────────────────────
echo "[7/8] Configuring avahi-daemon..."
sudo cp "$INSTALL_DIR/deployment/avahi-brain.service" \
    /etc/avahi/services/brain.service
sudo systemctl enable avahi-daemon
sudo systemctl restart avahi-daemon
echo "  mybrain.local will be advertised on the LAN."

# ── 8. systemd service ─────────────────────────────────────────────────────
echo "[8/8] Installing brain.service..."
# Patch the service file with the actual install dir and user
UNIT_TMP=$(mktemp)
sed "s|REPLACE_DIR|$INSTALL_DIR|g; s|REPLACE_USER|$INSTALL_USER|g" \
    "$INSTALL_DIR/deployment/brain.service" > "$UNIT_TMP"
sudo cp "$UNIT_TMP" /etc/systemd/system/brain.service
rm "$UNIT_TMP"
sudo systemctl daemon-reload
sudo systemctl enable brain
sudo systemctl restart brain
echo "  brain.service enabled and started."

# ── Verification ─────────────────────────────────────────────────────────────
echo ""
echo "=== Verifying installation ==="
cd "$INSTALL_DIR"
"$VENV_DIR/bin/python" execution/verify_setup.py

echo ""
echo "=== Installation complete ==="
echo ""
echo "  Web UI   : http://mybrain.local  (or http://$(hostname -I | awk '{print $1}'))"
echo "  Setup    : http://mybrain.local/setup"
echo "  Token    : cat $ENV_FILE | grep INGEST_TOKEN"
echo ""
echo "Service status:"
systemctl is-active brain  && echo "  brain  : running ✓" || echo "  brain  : FAILED ✗"
systemctl is-active ollama && echo "  ollama : running ✓" || echo "  ollama : FAILED ✗"
echo ""
