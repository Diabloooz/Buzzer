#!/usr/bin/env python3
"""
Buzzer Pi — web server
Serves dashboard, data.json, control panel, and trigger endpoints.
Runs on port 8080.
"""

import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

BASE_DIR   = Path(__file__).parent
DATA_FILE  = BASE_DIR / "data.json"
LOG_FILE   = BASE_DIR / "fetch.log"
DASH_FILE  = BASE_DIR / "dashboard" / "dashboard.html"
CTRL_FILE  = BASE_DIR / "dashboard" / "control.html"
FETCH_SCRIPT   = BASE_DIR / "fetch.py"
HEALTH_STATE   = BASE_DIR / "health_state.json"
PORT       = 8080


def read_tail(path, n=50):
    if not path.exists():
        return ""
    lines = path.read_text(errors="replace").splitlines()
    return "\n".join(lines[-n:])


def data_status():
    if not DATA_FILE.exists():
        return {"ok": False, "error": "data.json not found", "age_seconds": None}
    try:
        d = json.loads(DATA_FILE.read_text())
        fetched_at = d.get("fetched_at")
        if fetched_at:
            ts = datetime.fromisoformat(fetched_at.replace("Z", "+00:00"))
            age = (datetime.now(timezone.utc) - ts).total_seconds()
        else:
            age = None
        return {
            "ok":           True,
            "fetched_at":   fetched_at,
            "age_seconds":  int(age) if age is not None else None,
            "gold_fetched_at": d.get("gold_fetched_at"),
        }
    except Exception as e:
        return {"ok": False, "error": str(e), "age_seconds": None}



HEALTH_SERVICES = ["buzzer-server", "buzzer-fetch.timer", "buzzer-gold.timer"]


def health_data():
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

    def svc_statuses():
        result = {}
        for svc in HEALTH_SERVICES:
            try:
                r = subprocess.run(["systemctl", "is-active", svc],
                                   capture_output=True, text=True)
                result[svc] = r.stdout.strip()
            except Exception:
                result[svc] = "unknown"
        return result

    temp = cpu_temp()
    ram  = ram_pct()
    disk = disk_pct()
    svcs = svc_statuses()

    def status(val, threshold):
        if val is None: return "unknown"
        if val < threshold * 0.9: return "ok"
        if val < threshold: return "warn"
        return "alert"

    last_checked = None
    if HEALTH_STATE.exists():
        try:
            hs = json.loads(HEALTH_STATE.read_text())
            last_checked = hs.get("last_checked")
        except Exception:
            pass

    return {
        "checked_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "cpu_temp":   {"value": temp,  "threshold": 70,  "status": status(temp, 70)},
        "ram_pct":    {"value": ram,   "threshold": 85,  "status": status(ram,  85)},
        "disk_pct":   {"value": disk,  "threshold": 80,  "status": status(disk, 80)},
        "services":   {svc: {"status": st, "ok": st == "active"} for svc, st in svcs.items()},
    }

class Handler(BaseHTTPRequestHandler):

    def log_message(self, fmt, *args):
        pass  # suppress default access log noise

    def send(self, code, content_type, body):
        if isinstance(body, str):
            body = body.encode()
        self.send_response(code)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        path = self.path.split("?")[0]

        if path == "/" or path == "/index.html":
            if DASH_FILE.exists():
                self.send(200, "text/html; charset=utf-8", DASH_FILE.read_text())
            else:
                self.send(404, "text/plain", "dashboard.html not found")

        elif path == "/control" or path == "/control.html":
            if CTRL_FILE.exists():
                self.send(200, "text/html; charset=utf-8", CTRL_FILE.read_text())
            else:
                self.send(404, "text/plain", "control.html not found")

        elif path == "/data.json":
            if DATA_FILE.exists():
                self.send(200, "application/json", DATA_FILE.read_text())
            else:
                self.send(404, "application/json", '{"error":"no data yet"}')

        elif path == "/health":
            self.send(200, "application/json", json.dumps(health_data()))

        elif path == "/logs":
            self.send(200, "text/plain; charset=utf-8", read_tail(LOG_FILE, 50))

        elif path == "/status":
            self.send(200, "application/json", json.dumps(data_status()))

        else:
            self.send(404, "text/plain", "not found")

    def do_POST(self):
        path = self.path.split("?")[0]

        if path == "/fetch":
            try:
                subprocess.Popen(
                    [sys.executable, str(FETCH_SCRIPT)],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
                self.send(200, "application/json", '{"ok":true,"message":"fetch triggered"}')
            except Exception as e:
                self.send(500, "application/json", json.dumps({"ok": False, "error": str(e)}))
        else:
            self.send(404, "text/plain", "not found")


if __name__ == "__main__":
    server = HTTPServer(("0.0.0.0", PORT), Handler)
    print(f"Buzzer server running on port {PORT}", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
