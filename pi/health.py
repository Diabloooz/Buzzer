#!/usr/bin/env python3
"""
Buzzer Pi -- health monitor
Checks CPU temp, RAM, disk, and service status every 5 minutes.
Sends Telegram alerts when thresholds are breached, with cooldown logic.
"""

import json
import logging
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

import requests

BASE_DIR   = Path(__file__).parent
LOG_FILE   = BASE_DIR / "fetch.log"
STATE_FILE = BASE_DIR / "health_state.json"
ENV_FILE   = BASE_DIR / ".env"

THRESHOLDS = {
    "cpu_temp": 70.0,
    "ram_pct":  85.0,
    "disk_pct": 80.0,
}
SERVICES = ["buzzer-server", "buzzer-fetch.timer", "buzzer-gold.timer"]
COOLDOWN_CHECKS = 3

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-7s  %(message)s",
    datefmt="%Y-%m-%dT%H:%M:%SZ",
    handlers=[logging.FileHandler(LOG_FILE), logging.StreamHandler(sys.stdout)],
)
log = logging.getLogger(__name__)



def load_env():
    if ENV_FILE.exists():
        for line in ENV_FILE.read_text().splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, _, v = line.partition("=")
                os.environ.setdefault(k.strip(), v.strip())


def cpu_temp():
    try:
        raw = Path("/sys/class/thermal/thermal_zone0/temp").read_text().strip()
        return round(int(raw) / 1000, 1)
    except Exception:
        return None


def ram_pct():
    try:
        info = {}
        for line in Path("/proc/meminfo").read_text().splitlines():
            k, _, v = line.partition(":")
            info[k.strip()] = int(v.strip().split()[0])
        total = info["MemTotal"]
        available = info["MemAvailable"]
        return round((total - available) / total * 100, 1)
    except Exception:
        return None


def disk_pct():
    try:
        out = subprocess.check_output(["df", "/", "--output=pcent"], text=True)
        return float(out.splitlines()[1].strip().rstrip("%"))
    except Exception:
        return None


def service_statuses():
    statuses = {}
    for svc in SERVICES:
        try:
            result = subprocess.run(["systemctl", "is-active", svc],
                                    capture_output=True, text=True)
            statuses[svc] = result.stdout.strip()
        except Exception:
            statuses[svc] = "unknown"
    return statuses


def collect_health():
    return {
        "checked_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "cpu_temp":   cpu_temp(),
        "ram_pct":    ram_pct(),
        "disk_pct":   disk_pct(),
        "services":   service_statuses(),
    }


def load_state():
    if STATE_FILE.exists():
        try:
            return json.loads(STATE_FILE.read_text())
        except Exception:
            pass
    return {}


def save_state(state):
    STATE_FILE.write_text(json.dumps(state, indent=2))


def fmt_gmt3(dt_utc=None):
    """Format a UTC datetime as DD-Mon-YY HH:MM GMT+3."""
    from datetime import timedelta
    if dt_utc is None:
        dt_utc = datetime.now(timezone.utc)
    gmt3 = dt_utc + timedelta(hours=3)
    return gmt3.strftime("%d-%b-%y %H:%M GMT+3")


def tg_send(text):
    token = os.environ.get("TELEGRAM_BOT_TOKEN", "")
    chat  = os.environ.get("TELEGRAM_CHAT_ID", "")
    try:
        url = f"https://api.telegram.org/bot{token}/sendMessage"
        r = requests.post(url, json={"chat_id": chat, "text": text, "parse_mode": "HTML"},
                          timeout=10)
        r.raise_for_status()
        log.info("Telegram alert sent")
    except Exception as e:
        log.error(f"Telegram send failed: {e}")


def check_alerts(health, state):
    alerts = []
    new_state = dict(state)

    temp = health["cpu_temp"]
    if temp is not None and temp >= THRESHOLDS["cpu_temp"]:
        count = state.get("cpu_temp_breach", 0) + 1
        new_state["cpu_temp_breach"] = count
        if count == 1 or count % COOLDOWN_CHECKS == 0:
            alerts.append(
                f"\U0001f321 CPU temp {temp}°C ↑ (threshold {THRESHOLDS['cpu_temp']}°C) "
                f"-- reply /reboot to reboot Pi or /restart to restart Buzzer services only"
            )
    else:
        new_state["cpu_temp_breach"] = 0

    ram = health["ram_pct"]
    if ram is not None and ram >= THRESHOLDS["ram_pct"]:
        count = state.get("ram_pct_breach", 0) + 1
        new_state["ram_pct_breach"] = count
        if count == 1 or count % COOLDOWN_CHECKS == 0:
            alerts.append(
                f"\U0001f4be RAM usage {ram}% ↑ (threshold {THRESHOLDS['ram_pct']}%) "
                f"-- reply /reboot to reboot Pi"
            )
    else:
        new_state["ram_pct_breach"] = 0

    disk = health["disk_pct"]
    if disk is not None and disk >= THRESHOLDS["disk_pct"]:
        count = state.get("disk_pct_breach", 0) + 1
        new_state["disk_pct_breach"] = count
        if count == 1 or count % COOLDOWN_CHECKS == 0:
            alerts.append(
                f"\U0001f4bf Disk usage {disk}% ↑ (threshold {THRESHOLDS['disk_pct']}%) "
                f"-- free up space on the Pi"
            )
    else:
        new_state["disk_pct_breach"] = 0

    dead = [s for s, st in health["services"].items() if st != "active"]
    if dead:
        count = state.get("services_breach", 0) + 1
        new_state["services_breach"] = count
        if count == 1 or count % COOLDOWN_CHECKS == 0:
            alerts.append(
                f"⚠️ Service(s) down: {', '.join(dead)} "
                f"-- reply /restart to restart Buzzer services or /reboot to reboot Pi"
            )
    else:
        new_state["services_breach"] = 0

    return alerts, new_state


if __name__ == "__main__":
    load_env()
    log.info("=== health check start ===")

    health = collect_health()
    log.info(
        f"cpu={health['cpu_temp']}C  ram={health['ram_pct']}%  "
        f"disk={health['disk_pct']}%  services={health['services']}"
    )

    state = load_state()
    alerts, new_state = check_alerts(health, state)
    save_state(new_state)

    if alerts:
        ts = fmt_gmt3()
        msg = f"\U0001f6a8 <b>Buzzer Pi Alert</b>  <i>{ts}</i>\n\n" + "\n\n".join(alerts)
        tg_send(msg)
        log.info(f"Sent {len(alerts)} alert(s)")
    else:
        log.info("All metrics OK -- no alert sent")

    log.info("=== health check done ===")
