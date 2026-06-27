#!/usr/bin/env python3
"""
Buzzer Pi -- Telegram command bot
Listens for /status, /reboot, /restart commands via long-polling.
Runs as a persistent service.
"""

import json
import logging
import os
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import requests

BASE_DIR    = Path(__file__).parent
LOG_FILE    = BASE_DIR / "fetch.log"
DATA_FILE   = BASE_DIR / "data.json"
OFFSET_FILE = BASE_DIR / "bot_offset.json"
WELCOME_FILE = BASE_DIR / "bot_welcomed.flag"
ENV_FILE    = BASE_DIR / ".env"

SERVICES  = ["buzzer-server", "buzzer-fetch.timer", "buzzer-gold.timer"]

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



def fmt_gmt3(dt_utc=None):
    """Format a UTC datetime as DD-Mon-YY HH:MM GMT+3."""
    from datetime import timedelta
    if dt_utc is None:
        dt_utc = datetime.now(timezone.utc)
    gmt3 = dt_utc + timedelta(hours=3)
    return gmt3.strftime("%d-%b-%y %H:%M GMT+3")


def tg_send(text, chat_id=None):
    token = os.environ.get("TELEGRAM_BOT_TOKEN", "")
    cid = chat_id or os.environ.get("TELEGRAM_CHAT_ID", "")
    try:
        url = f"https://api.telegram.org/bot{token}/sendMessage"
        r = requests.post(url, json={"chat_id": cid, "text": text, "parse_mode": "HTML"},
                          timeout=10)
        r.raise_for_status()
    except Exception as e:
        log.error(f"tg_send failed: {e}")


def tg_get_updates(offset):
    try:
        token = os.environ.get("TELEGRAM_BOT_TOKEN", "")
        url = f"https://api.telegram.org/bot{token}/getUpdates"
        r = requests.get(url, params={"offset": offset, "timeout": 30}, timeout=40)
        r.raise_for_status()
        return r.json().get("result", [])
    except Exception as e:
        log.error(f"getUpdates failed: {e}")
        return []


def load_offset():
    if OFFSET_FILE.exists():
        try:
            return json.loads(OFFSET_FILE.read_text()).get("offset", 0)
        except Exception:
            pass
    return 0


def save_offset(offset):
    OFFSET_FILE.write_text(json.dumps({"offset": offset}))


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


def circle(val, threshold):
    if val is None:
        return "⚪"
    if val < threshold * 0.9:
        return "\U0001f7e2"
    if val < threshold:
        return "\U0001f7e1"
    return "\U0001f534"


def svc_circle(status):
    return "\U0001f7e2" if status == "active" else "\U0001f534"


def health_snapshot():
    temp = cpu_temp()
    ram  = ram_pct()
    disk = disk_pct()
    svcs = service_statuses()

    last_fetch = "no data"
    if DATA_FILE.exists():
        try:
            d = json.loads(DATA_FILE.read_text())
            if d.get("fetched_at"):
                ts = datetime.fromisoformat(d["fetched_at"].replace("Z", "+00:00"))
                age_min = int((datetime.now(timezone.utc) - ts).total_seconds() / 60)
                last_fetch = f"{fmt_gmt3(ts)} ({age_min}m ago)"
        except Exception:
            pass

    checked_at = fmt_gmt3()
    lines = [
        f"<b>\U0001f4ca Pi Health Snapshot</b>  <i>{checked_at}</i>",
        "",
        f"{circle(temp, 70)}  CPU temp:  {temp}C  (threshold 70C)",
        f"{circle(ram,  85)}  RAM usage: {ram}%  (threshold 85%)",
        f"{circle(disk, 80)}  Disk:      {disk}%  (threshold 80%)",
        "",
    ]
    for svc, status in svcs.items():
        lines.append(f"{svc_circle(status)}  {svc}: {status}")
    lines += ["", f"⏱ Last fetch: {last_fetch}"]
    return "\n".join(lines)


def wait_services_up(timeout=120):
    deadline = time.time() + timeout
    while time.time() < deadline:
        if all(s == "active" for s in service_statuses().values()):
            return True
        time.sleep(5)
    return False


def cmd_status(chat_id):
    tg_send(health_snapshot(), chat_id)


def cmd_restart(chat_id):
    tg_send("\U0001f504 Restarting Buzzer services...", chat_id)
    log.info("CMD /restart received")
    try:
        for svc in SERVICES:
            subprocess.run(["sudo", "systemctl", "restart", svc], check=True)
        time.sleep(3)
        if wait_services_up(60):
            tg_send("✅ Services restarted successfully.\n\n" + health_snapshot(), chat_id)
        else:
            tg_send("⚠️ Restart issued but some services may still be starting. Check /status.", chat_id)
    except Exception as e:
        tg_send(f"❌ Restart failed: {e}", chat_id)
        log.error(f"Restart failed: {e}")


def cmd_reboot(chat_id):
    tg_send("\U0001f501 Rebooting Pi now... I will message you when services are back online.", chat_id)
    log.info("CMD /reboot received")
    time.sleep(2)
    subprocess.run(["sudo", "reboot"])


WELCOME_MSG = (
    "<b>Buzzer Pi Bot is online!</b>\n\n"
    "I monitor your Pi health and alert you when something needs attention.\n\n"
    "<b>Commands:</b>\n\n"
    "/status -- Instant health snapshot: CPU temp, RAM, disk, service statuses, last fetch time\n\n"
    "/restart -- Restart all Buzzer services. Confirms when done.\n\n"
    "/reboot -- Reboot the Pi. I will message you once services are back online.\n\n"
    "<b>Automatic alerts:</b>\n"
    "CPU temp >= 70C, RAM >= 85%, Disk >= 80%, any service down\n"
    "Alerts repeat after 15 minutes if still in breach.\n\n"
    "<b>Daily summary:</b> Every day at 21:00 AST (18:00 UTC)."
)


def send_welcome_if_needed():
    if not WELCOME_FILE.exists():
        tg_send(WELCOME_MSG)
        WELCOME_FILE.write_text(datetime.now(timezone.utc).isoformat())
        log.info("Welcome message sent")


def parse_command(text):
    if not text:
        return None
    t = text.strip().lstrip("/").lower().split()[0]
    if t == "status":
        return "status"
    if t == "reboot":
        return "reboot"
    if t == "restart":
        return "restart"
    return None


def main():
    load_env()
    log.info("=== buzzer-bot start ===")
    send_welcome_if_needed()
    offset = load_offset()
    while True:
        updates = tg_get_updates(offset)
        for upd in updates:
            offset = upd["update_id"] + 1
            save_offset(offset)
            msg = upd.get("message") or upd.get("edited_message")
            if not msg:
                continue
            chat_id = str(msg["chat"]["id"])
            text = msg.get("text", "")
            cmd = parse_command(text)
            if cmd is None:
                continue
            log.info(f"Command '{cmd}' from chat {chat_id}")
            if cmd == "status":
                cmd_status(chat_id)
            elif cmd == "restart":
                cmd_restart(chat_id)
            elif cmd == "reboot":
                cmd_reboot(chat_id)
        time.sleep(1)


if __name__ == "__main__":
    main()
