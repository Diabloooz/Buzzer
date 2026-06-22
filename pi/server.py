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
FETCH_SCRIPT = BASE_DIR / "fetch.py"
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
