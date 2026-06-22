# Buzzer Pi — Technical Build Report

> Generated: 2026-06-22  
> Session: Buzzer Pi initial build & deployment

---

## 1. Hardware & OS

| Field | Value |
|---|---|
| **Device** | Raspberry Pi 3 Model B (not Pi 4 — confirmed during setup) |
| **Architecture** | ARMv7l (32-bit) |
| **OS** | Raspberry Pi OS Lite, 32-bit |
| **Kernel** | `Linux 6.18.34+rpt-rpi-v7 #1 SMP Raspbian 1:6.18.34-1+rpt1 (2026-06-09) armv7l` |
| **Hostname** | `buzzer-pi` |
| **Primary user** | `pi` |
| **Home directory** | `/home/pi/` |
| **Repo root on Pi** | `/home/pi/buzzer/` |
| **Working directory** | `/home/pi/buzzer/pi/` |

---

## 2. File Structure

All application files live under `/home/pi/buzzer/pi/` — the `pi/` subdirectory of the cloned GitHub repo (`diabloooz/buzzer`, branch `claude/youthful-euler-teysly`).

```
/home/pi/buzzer/                        ← git repo root
├── pi/                                 ← all application files
│   ├── fetch.py                        ← market rate fetch script (Python 3)
│   ├── server.py                       ← HTTP web server (Python 3, stdlib only)
│   ├── setup.sh                        ← one-shot deployment script (Bash)
│   ├── .env                            ← API keys (gitignored, created on Pi)
│   ├── .env.example                    ← key template committed to repo
│   ├── .gitignore                      ← excludes .env, data.json, logs, __pycache__
│   ├── README.md                       ← this file
│   ├── data.json                       ← live market data output (gitignored)
│   ├── data.json.tmp                   ← atomic write buffer (gitignored)
│   ├── fetch.log                       ← fetch script log, max 500 lines (gitignored)
│   ├── dashboard/
│   │   ├── dashboard.html              ← Buzzer market rates dashboard (HTML/JS)
│   │   └── control.html               ← admin control panel (HTML/JS)
│   └── systemd/
│       ├── buzzer-server.service       ← web server systemd unit
│       ├── buzzer-fetch.service        ← rates fetch oneshot unit
│       ├── buzzer-fetch.timer          ← 30-min timer for rates fetch
│       ├── buzzer-gold.service         ← gold fetch oneshot unit
│       └── buzzer-gold.timer          ← 8-hour timer for gold fetch
```

---

## 3. Data Sources

### USD / EGP
| Field | Value |
|---|---|
| **Source** | FloatRates |
| **Endpoint** | `https://www.floatrates.com/daily/usd.json` |
| **Auth** | None — completely free, no key required |
| **Method** | `GET`, JSON response |
| **Fetch frequency** | Every 30 minutes |
| **Free tier limit** | Unlimited |
| **Update frequency (upstream)** | Hourly |
| **Response field used** | `d["egp"]["rate"]` |

### SAR / EGP
| Field | Value |
|---|---|
| **Source** | Computed (not a separate API call) |
| **Method** | Cross-rate: `USD_EGP ÷ 3.75` |
| **Rationale** | SAR is pegged to USD at a fixed rate of 3.75, making this mathematically exact |
| **Fetch frequency** | Derived from FloatRates call — every 30 minutes |

### XAU / USD (Gold)
| Field | Value |
|---|---|
| **Source** | GoldAPI.io |
| **Endpoint** | `https://www.goldapi.io/api/XAU/USD` |
| **Auth** | Header: `x-access-token: <GOLDAPI_KEY>` |
| **Method** | `GET`, JSON response |
| **Fetch frequency** | Every **8 hours** |
| **Free tier limit** | 100 requests/month |
| **Budget math** | 3 req/day × 31 days = 93 req/month ✓ (6h would exceed: 4 × 31 = 124) |
| **Response field used** | `d["price"]` |

### Crude Oil / WTI (originally intended as Brent)
| Field | Value |
|---|---|
| **Source** | API-Ninjas |
| **Endpoint** | `https://api.api-ninjas.com/v1/commodityprice?name=crude_oil` |
| **Auth** | Header: `X-Api-Key: <APININJAS_KEY>` |
| **Method** | `GET`, JSON response |
| **Fetch frequency** | Every 30 minutes |
| **Free tier limit** | 10,000 requests/month |
| **Budget math** | 2 req/hr × 24 × 31 = 1,488/month — well within limit |
| **Response field used** | `d["price"]` |
| **⚠ Known issue** | See Section 7 — Brent crude is premium-only on API-Ninjas free tier |

---

## 4. fetch.py Logic

**Location:** `/home/pi/buzzer/pi/fetch.py`  
**Runtime:** Python 3 (system Python on Pi OS)  
**Dependency:** `python3-requests` (installed via apt)

### Modes

The script has two modes controlled by a CLI flag:

```
python3 fetch.py           # rates mode: FX + crude (runs every 30 min)
python3 fetch.py --gold    # gold mode: XAU/USD only (runs every 8 hours)
```

### Rates Mode Flow (`run_rates()`)

```
1. Load .env file → set GOLDAPI_KEY, APININJAS_KEY as env vars
2. Load existing data.json (to preserve gold data across calls)
3. Fetch FloatRates → USD/EGP and SAR/EGP (cross-computed)
4. Fetch API-Ninjas → WTI crude price
5. Validation:
   - If USD/EGP (FX) is None → log error, exit(1), data.json untouched
   - If crude is None → log warning, use last known value from existing data.json
6. Build data dict:
   {
     "fetched_at":      ISO8601 UTC timestamp,
     "usd_egp":         float (4 decimal places),
     "sar_egp":         float (4 decimal places),
     "brent_usd":       float (2 decimal places) or preserved from last fetch,
     "xau_usd":         preserved from last gold fetch,
     "gold_fetched_at": preserved from last gold fetch
   }
7. Write to data.json.tmp (atomic buffer)
8. On success: os.rename(data.json.tmp → data.json)
9. On any exception: exit without touching data.json
```

### Gold Mode Flow (`run_gold()`)

```
1. Load .env file
2. Load existing data.json (to preserve FX + crude data)
3. Fetch GoldAPI.io → XAU/USD price
4. If fetch fails → log error, exit(1), data.json untouched
5. Merge: {**existing_data, "xau_usd": price, "gold_fetched_at": now}
6. Write atomically via .tmp → rename
```

### Log Rotation

- All output goes to `/home/pi/buzzer/pi/fetch.log` and stdout
- After every run, log file is trimmed to last **500 lines**
- Format: `YYYY-MM-DDTHH:MM:SSZ  LEVEL    message`

### Failure Handling Summary

| Failure scenario | Behaviour |
|---|---|
| FloatRates unreachable | Exit without writing. data.json unchanged. |
| API-Ninjas unreachable | Preserve last crude value. FX still written. |
| GoldAPI unreachable | Exit without writing. data.json unchanged. |
| data.json.tmp write fails | Exception propagates, data.json safe. |
| Partial JSON from API | KeyError caught, treated as fetch failure. |

---

## 5. server.py Logic

**Location:** `/home/pi/buzzer/pi/server.py`  
**Runtime:** Python 3 stdlib only (`http.server`) — no pip packages needed  
**Port:** `8080`  
**Bind:** `0.0.0.0` (all interfaces, but firewall restricts to Tailscale)

### Endpoints

| Method | Path | Response | Description |
|---|---|---|---|
| `GET` | `/` | `dashboard.html` | Main market rates dashboard |
| `GET` | `/control` | `control.html` | Admin control panel |
| `GET` | `/data.json` | JSON file | Current market data |
| `GET` | `/logs` | Plain text | Last 50 lines of fetch.log |
| `GET` | `/status` | JSON | `{ok, fetched_at, age_seconds, gold_fetched_at}` |
| `POST` | `/fetch` | JSON | Triggers `fetch.py` as background subprocess |

### Notes
- No framework — pure Python stdlib `BaseHTTPRequestHandler`
- All responses include `Cache-Control: no-store`
- Access logging suppressed (too noisy for systemd journal)
- `/fetch` POST spawns `fetch.py` via `subprocess.Popen` (non-blocking — returns immediately, fetch runs in background)

---

## 6. Systemd Services

All unit files installed at `/etc/systemd/system/`. All enabled on `multi-user.target`.

### buzzer-server.service
```
Purpose:      Runs server.py (web server) permanently
Type:         simple
User:         pi
WorkingDir:   /home/pi/buzzer/pi
ExecStart:    /usr/bin/python3 /home/pi/buzzer/pi/server.py
Restart:      always
RestartSec:   5s
After:        network-online.target tailscaled.service
```

### buzzer-fetch.service + buzzer-fetch.timer
```
Purpose:      Fetches FX + crude rates
Type:         oneshot
User:         pi
WorkingDir:   /home/pi/buzzer/pi
ExecStart:    /usr/bin/python3 /home/pi/buzzer/pi/fetch.py
Timer:        OnBootSec=60, then every 30 minutes
Persistent:   true (catches up missed runs after power outage)
After:        network-online.target tailscaled.service
```

### buzzer-gold.service + buzzer-gold.timer
```
Purpose:      Fetches gold price (XAU/USD)
Type:         oneshot
User:         pi
WorkingDir:   /home/pi/buzzer/pi
ExecStart:    /usr/bin/python3 /home/pi/buzzer/pi/fetch.py --gold
Timer:        OnBootSec=90, then every 8 hours
Persistent:   true
After:        network-online.target tailscaled.service
```

### Boot Order
```
network-online.target → tailscaled.service → buzzer-* services
```
This ensures Tailscale is up before services start, and internet is available before fetches run. The 60s/90s `OnBootSec` delays provide additional buffer for network stabilisation.

---

## 7. Known Issues & Deferred Fixes

### Issue 1 — WTI instead of Brent Crude

**Original requirement:** Brent crude (BZ=F)  
**Current behaviour:** WTI crude (West Texas Intermediate)  
**Root cause:** API-Ninjas free tier does not include Brent crude. Response during setup:
```
"The commodity 'brent crude' is available for premium users only."
Available free commodities include: crude_oil (WTI)
```
**Current workaround:** Using `crude_oil` (WTI) from API-Ninjas free tier.  
**Dashboard label:** Updated to "Crude Oil · WTI" to be accurate.  
**data.json key:** Still named `brent_usd` internally (legacy from initial design).  
**Fix if needed:** Upgrade API-Ninjas to paid tier, or find a free Brent source (EIA API is an option — requires separate integration).

---

### Issue 2 — Partial Fetch Resilience (resolved in build, documented here)

**Original behaviour:** `run_rates()` required BOTH FloatRates AND crude to succeed before writing `data.json`. If Brent (now WTI) failed, FX rates were also discarded.  
**Problem observed:** During initial setup, Brent returned 400 error → `usd_egp` and `sar_egp` were never written → dashboard showed "no data yet" for all FX cards even though FloatRates worked fine.  
**Fix applied:** FX is now the only critical dependency. Crude is best-effort:
```python
# FX rates are critical — abort only if missing
if usd_egp is None:
    log.error("FX fetch failed — data.json NOT updated")
    sys.exit(1)

# Crude: use new value if fetched, else preserve last known
"brent_usd": round(brent, 2) if brent is not None else existing.get("brent_usd")
```
**Current behaviour:** If crude fails, last known crude value is preserved in `data.json`. Dashboard shows amber stale indicator if data is >1 hour old.

---

## 8. SSH Access

### Connection Details
| Field | Value |
|---|---|
| **Pi user** | `pi` |
| **Pi Tailscale IP** | `100.87.60.118` |
| **SSH command** | `ssh pi@100.87.60.118` |
| **Auth method** | SSH key (ED25519, passwordless) |
| **Key location (laptop)** | `C:\Users\diabl\.ssh\id_ed25519` |
| **Key installed on Pi** | `~/.ssh/authorized_keys` |

### For Future Claude Code Sessions

To give a new Claude Code session full access to the Pi:

1. The session must run **locally on the Windows laptop** ("diablo" — `100.96.167.64` on Tailscale), NOT as a remote/cloud session
2. The laptop must have Tailscale running and connected
3. SSH key at `C:\Users\diabl\.ssh\id_ed25519` must be present (already set up)
4. Test with: `ssh pi@100.87.60.118 echo "Pi reachable"`

**Why cloud/remote Claude Code sessions cannot control the Pi:**  
The Pi is only accessible within the Tailscale private network. Anthropic's cloud containers running remote Claude Code sessions are not on the user's Tailscale network and have no SSH client installed. Only a local Claude Code session on a Tailscale-enrolled device can SSH to the Pi.

---

## 9. Tailscale Setup

### Enrolled Devices

| Machine | Tailscale IP | OS | Status | Key Expiry |
|---|---|---|---|---|
| `buzzer-pi` | `100.87.60.118` | Raspberry Pi OS (ARMv7) | ✅ Connected | **Disabled** ✓ |
| `diablo` | `100.96.167.64` | Windows 11 25H2 | Connected (intermittent) | Default |
| `pixel-8-pro` | `100.103.247.98` | Android 17 | ✅ Connected | Default |

### Key Notes
- **Key expiry is disabled on `buzzer-pi`** — this is critical. Without this, Tailscale access expires after 180 days and the Pi becomes unreachable remotely with no physical access available.
- The dashboard and SSH are accessible from any enrolled device from anywhere in the world
- No router port forwarding required — Tailscale handles NAT traversal

### Accessing the Dashboard Remotely
1. Ensure Tailscale is running on your device (phone or laptop)
2. Open browser → `http://100.87.60.118:8080/`
3. Control panel → `http://100.87.60.118:8080/control`

---

## 10. Maintenance Guide

### Update API Keys
```bash
ssh pi@100.87.60.118
nano /home/pi/buzzer/pi/.env
# Edit keys, then Ctrl+X → Y → Enter to save
sudo systemctl restart buzzer-server
```

### Restart Services
```bash
sudo systemctl restart buzzer-server          # web server
sudo systemctl restart buzzer-fetch.timer     # rates fetch timer
sudo systemctl restart buzzer-gold.timer      # gold fetch timer
```

### Check Service Status
```bash
sudo systemctl status buzzer-server
sudo systemctl status buzzer-fetch.timer
sudo systemctl status buzzer-gold.timer
```

### View Logs
```bash
# Fetch script log (structured, rotating)
tail -50 /home/pi/buzzer/pi/fetch.log

# Systemd journal (server process)
journalctl -u buzzer-server -f

# Systemd journal (fetch runs)
journalctl -u buzzer-fetch -n 20
journalctl -u buzzer-gold -n 10
```

### Trigger a Manual Fetch
```bash
# FX + crude (immediate)
cd /home/pi/buzzer/pi && python3 fetch.py

# Gold only (immediate)
cd /home/pi/buzzer/pi && python3 fetch.py --gold
```

Or use the control panel in browser: `http://100.87.60.118:8080/control` → "Fetch Now"

### Deploy Code Updates from GitHub
```bash
ssh pi@100.87.60.118
cd /home/pi/buzzer && git pull
sudo systemctl restart buzzer-server
```

### View Current data.json
```bash
cat /home/pi/buzzer/pi/data.json | python3 -m json.tool
```

### Reboot Pi (if needed)
```bash
sudo reboot
# All services auto-start on boot — no manual intervention needed
```

---

## Appendix — data.json Schema

```json
{
  "fetched_at":      "2026-06-22T21:58:21Z",   // ISO8601 UTC — last FX+crude fetch
  "usd_egp":         49.8463,                   // USD per 1 EGP (4 decimal places)
  "sar_egp":         13.2923,                   // SAR per 1 EGP (4 decimal places)
  "brent_usd":       78.45,                     // WTI crude USD/barrel (2 decimal places)
  "xau_usd":         4190.77,                   // Gold USD/troy oz (2 decimal places)
  "gold_fetched_at": "2026-06-22T21:58:23Z"    // ISO8601 UTC — last gold fetch
}
```

---

## Appendix — GitHub Repository

| Field | Value |
|---|---|
| **Repo** | `github.com/diabloooz/buzzer` |
| **Branch** | `claude/youthful-euler-teysly` |
| **Pi files** | `pi/` subdirectory |
| **Clone command** | `git clone --branch claude/youthful-euler-teysly https://github.com/diabloooz/buzzer.git /home/pi/buzzer` |
