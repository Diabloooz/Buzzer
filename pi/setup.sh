#!/bin/bash
# Buzzer Pi — one-shot setup script
# Run as pi user: bash setup.sh
# You will be prompted for your API keys.

set -e
BUZZER_DIR="/home/pi/buzzer"
REPO="https://github.com/diabloooz/buzzer"

echo ""
echo "=== Buzzer Pi Setup ==="
echo ""

# ── 1. Install dependencies ───────────────────────────────────────────────────
echo "[1/6] Installing Python dependencies..."
pip3 install --quiet requests

# ── 2. API keys ───────────────────────────────────────────────────────────────
echo ""
echo "[2/6] API Key Setup"
echo "      (keys are stored locally in .env — never sent anywhere)"
echo ""

if [ -f "$BUZZER_DIR/.env" ]; then
  echo "      .env already exists — skipping (delete it to re-enter keys)"
else
  read -rp "      GoldAPI.io key   : " GOLDAPI_KEY
  read -rp "      API-Ninjas key   : " APININJAS_KEY
  cat > "$BUZZER_DIR/.env" <<EOF
GOLDAPI_KEY=${GOLDAPI_KEY}
APININJAS_KEY=${APININJAS_KEY}
EOF
  echo "      .env written."
fi

# ── 3. Install systemd services ───────────────────────────────────────────────
echo ""
echo "[3/6] Installing systemd services..."
sudo cp "$BUZZER_DIR/systemd/"*.service /etc/systemd/system/
sudo cp "$BUZZER_DIR/systemd/"*.timer   /etc/systemd/system/
sudo systemctl daemon-reload

# ── 4. Enable & start services ────────────────────────────────────────────────
echo "[4/6] Enabling services..."
sudo systemctl enable buzzer-server.service
sudo systemctl enable buzzer-fetch.timer
sudo systemctl enable buzzer-gold.timer
sudo systemctl start  buzzer-server.service
sudo systemctl start  buzzer-fetch.timer
sudo systemctl start  buzzer-gold.timer
echo "      Services enabled and started."

# ── 5. Firewall (UFW) ─────────────────────────────────────────────────────────
echo ""
echo "[5/6] Configuring firewall (SSH via Tailscale only)..."
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
cd "$BUZZER_DIR"
python3 fetch.py && echo "      FX + Crude fetch OK" || echo "      FX + Crude fetch FAILED (check .env keys)"
python3 fetch.py --gold && echo "      Gold fetch OK" || echo "      Gold fetch FAILED (check GoldAPI key)"

# ── Done ──────────────────────────────────────────────────────────────────────
echo ""
TAILSCALE_IP=$(tailscale ip -4 2>/dev/null || echo "unknown — check tailscale.com/admin")
echo "======================================================"
echo " Setup complete!"
echo " Dashboard : http://${TAILSCALE_IP}:8080/"
echo " Control   : http://${TAILSCALE_IP}:8080/control"
echo " SSH       : ssh pi@${TAILSCALE_IP}"
echo ""
echo " IMPORTANT: Go to tailscale.com/admin → Machines"
echo "            → buzzer-pi → Disable key expiry"
echo "======================================================"
echo ""
