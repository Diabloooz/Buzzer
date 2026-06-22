# Buzzer Pi

Always-on market data server. Raspberry Pi 4, KSA.

---

## Access

| What | Address |
|---|---|
| Dashboard | `http://[TAILSCALE_IP]:8080/` |
| Control Panel | `http://[TAILSCALE_IP]:8080/control` |
| SSH | `ssh pi@[TAILSCALE_IP]` |

> **Tailscale IP**: update this after setup — find it at tailscale.com/admin → Machines → buzzer-pi
> `TAILSCALE_IP=`

---

## Service Commands

```bash
# Status
sudo systemctl status buzzer-server
sudo systemctl status buzzer-fetch.timer
sudo systemctl status buzzer-gold.timer

# Restart
sudo systemctl restart buzzer-server
sudo systemctl restart buzzer-fetch.timer

# View live logs
journalctl -u buzzer-server -f
journalctl -u buzzer-fetch -f

# Manual fetch (FX + Crude)
cd /home/pi/buzzer && python3 fetch.py

# Manual gold fetch
cd /home/pi/buzzer && python3 fetch.py --gold
```

---

## Update API Keys

```bash
nano /home/pi/buzzer/.env
# Edit, save (Ctrl+X → Y → Enter)
sudo systemctl restart buzzer-server
```

---

## Data Sources & Schedule

| Rate | Source | Frequency |
|---|---|---|
| USD/EGP | floatrates.com (free, no auth) | Every 30 min |
| SAR/EGP | Computed: USD/EGP ÷ 3.75 | Every 30 min |
| Brent Crude | API-Ninjas (api-ninjas.com) | Every 30 min |
| Gold XAU/USD | GoldAPI.io (100 req/month limit) | Every 6 hours |

---

## For Future Claude Code Sessions

SSH in first:
```bash
ssh pi@[TAILSCALE_IP]
```
Then start a Claude Code session and provide this README path:
`/home/pi/buzzer/README.md`

---

## Deploy Updates from GitHub

```bash
cd /home/pi/buzzer
git pull
sudo systemctl restart buzzer-server
```
