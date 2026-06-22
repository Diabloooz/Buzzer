#!/bin/bash
# Buzzer Pi — one-shot setup script
# Run from /home/pi/buzzer/pi/: bash setup.sh

set -e
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ENV_FILE="$SCRIPT_DIR/.env"

echo ""
echo "=== Buzzer Pi Setup ==="
echo "    Working from: $SCRIPT_DIR"
echo ""

# ── 1. Install dependencies ───────────────────────────────────────────────────
echo "[1/6] Installing Python dependencies..."
sudo apt-get install -y python3-requests -q
echo "      python3-requests installed."

# ── 2. API keys ───────────────────────────────────────────────────────────────
echo ""
echo "[2/6] API Key Setup"

if [ -f "$ENV_FILE" ]; then
  echo "      .env already exists — skipping (delete it to re-enter keys)"
else
  read -rp "      GoldAPI.io key   : " GOLDAPI_KEY
  read -rp "      API-Ninjas key   : " APININJAS_KEY
  cat > "$ENV_FILE" <<EOF
GOLDAPI_KEY=${GOLDAPI_KEY}
APININJAS_KEY=${APININJAS_KEY}
EOF
  chmod 600 "$ENV_FILE"
  echo "      .env written."
fi

# ── 3. Install systemd services ───────────────────────────────────────────────
echo ""
echo "[3/6] Installing systemd services..."
sudo cp "$SCRIPT_DIR/systemd/"*.service /etc/systemd/system/
sudo cp "$SCRIPT_DIR/systemd/"*.timer   /etc/systemd/system/
sudo systemctl daemon-reload
echo "      Services installed."

# ── 4. Enable & start services ────────────────────────────────────────────────
echo ""
echo "[4/6] Enabling and starting services..."
sudo systemctl enable buzzer-server.service
sudo systemctl enable buzzer-fetch.timer
sudo systemctl enable buzzer-gold.timer
sudo systemctl start  buzzer-server.service
sudo systemctl start  buzzer-fetch.timer
sudo systemctl start  buzzer-gold.timer
echo "      Services enabled and started."

# ── 5. Firewall ───────────────────────────────────────────────────────────────
echo ""
echo "[5/6] Configuring firewall (SSH + dashboard via Tailscale only)..."
sudo apt-get install -y ufw -q
sudo ufw allow in on tailscale0 to any port 22
sudo ufw allow in on tailscale0 to any port 8080
sudo ufw deny 22
sudo ufw deny 8080
sudo ufw --force enable
echo "      Firewall configured."

# ── 6. Initial fetch ──────────────────────────────────────────────────────────
echo ""
echo "[6/6] Running initial fetch..."
cd "$SCRIPT_DIR"
python3 fetch.py && echo "      FX + Crude fetch OK" || echo "      FX + Crude fetch FAILED — check .env keys"
python3 fetch.py --gold && echo "      Gold fetch OK" || echo "      Gold fetch FAILED — check GoldAPI key"

# ── Done ──────────────────────────────────────────────────────────────────────
TAILSCALE_IP=$(tailscale ip -4 2>/dev/null || echo "check tailscale.com/admin")
echo ""
echo "======================================================"
echo " Setup complete!"
echo " Dashboard : http://${TAILSCALE_IP}:8080/"
echo " Control   : http://${TAILSCALE_IP}:8080/control"
echo " SSH       : ssh pi@${TAILSCALE_IP}"
echo ""
echo " IMPORTANT: tailscale.com/admin → Machines"
echo "            → buzzer-pi → Disable key expiry"
echo "======================================================"
