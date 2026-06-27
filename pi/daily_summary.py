#!/usr/bin/env python3
"""
Buzzer Pi -- daily health summary
Sends a proactive Telegram health summary at 21:00 AST (18:00 UTC).
"""

import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

import requests

BASE_DIR  = Path(__file__).parent
DATA_FILE = BASE_DIR / "data.json"
ENV_FILE  = BASE_DIR / ".env"

SERVICES  = ["buzzer-server", "buzzer-fetch.timer", "buzzer-gold.timer"]


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
    except Exception as e:
        print(f"tg_send failed: {e}", file=sys.stderr)


def main():
    load_env()

    temp = cpu_temp()
    ram  = ram_pct()
    disk = disk_pct()
    svcs = service_statuses()

    now_ast = fmt_gmt3()

    all_ok = (
        (temp is None or temp < 70) and
        (ram  is None or ram  < 85) and
        (disk is None or disk < 80) and
        all(s == "active" for s in svcs.values())
    )

    headline = "\U0001f7e2 All systems normal" if all_ok else "\U0001f534 Attention needed"

    last_fetch = "no data"
    if DATA_FILE.exists():
        try:
            d = json.loads(DATA_FILE.read_text())
            if d.get("fetched_at"):
                ts = datetime.fromisoformat(d["fetched_at"].replace("Z", "+00:00"))
                last_fetch = fmt_gmt3(ts)
        except Exception:
            pass

    lines = [
        f"<b>\U0001f4c5 Daily Health Summary -- {now_ast}</b>",
        f"<b>{headline}</b>",
        "",
        f"{circle(temp, 70)}  CPU temp:  {temp}C",
        f"{circle(ram,  85)}  RAM usage: {ram}%",
        f"{circle(disk, 80)}  Disk:      {disk}%",
        "",
    ]
    for svc, status in svcs.items():
        lines.append(f"{svc_circle(status)}  {svc}: {status}")
    lines += ["", f"⏱ Last fetch: {last_fetch}"]

    tg_send("\n".join(lines))


if __name__ == "__main__":
    main()
