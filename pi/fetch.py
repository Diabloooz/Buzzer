#!/usr/bin/env python3
"""
Buzzer Pi — market rate fetcher
Usage:
  python fetch.py           → fetch FX + crude (run every 30 min)
  python fetch.py --gold    → fetch gold only  (run every 6 hours)
"""

import argparse
import json
import logging
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import requests

# ── Paths ─────────────────────────────────────────────────────────────────────
BASE_DIR  = Path(__file__).parent
DATA_FILE = BASE_DIR / "data.json"
TMP_FILE  = BASE_DIR / "data.json.tmp"
LOG_FILE  = BASE_DIR / "fetch.log"
ENV_FILE  = BASE_DIR / ".env"

# ── Logging ───────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-7s  %(message)s",
    datefmt="%Y-%m-%dT%H:%M:%SZ",
    handlers=[logging.FileHandler(LOG_FILE), logging.StreamHandler(sys.stdout)],
)
log = logging.getLogger(__name__)

LOG_MAX_LINES = 500


def trim_log():
    if not LOG_FILE.exists():
        return
    lines = LOG_FILE.read_text().splitlines()
    if len(lines) > LOG_MAX_LINES:
        LOG_FILE.write_text("\n".join(lines[-LOG_MAX_LINES:]) + "\n")


# ── Env loader ────────────────────────────────────────────────────────────────
def load_env():
    if ENV_FILE.exists():
        for line in ENV_FILE.read_text().splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, _, v = line.partition("=")
                os.environ.setdefault(k.strip(), v.strip())


# ── Helpers ───────────────────────────────────────────────────────────────────
def now_iso():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def load_existing():
    if DATA_FILE.exists():
        try:
            return json.loads(DATA_FILE.read_text())
        except Exception:
            pass
    return {}


def save(data):
    TMP_FILE.write_text(json.dumps(data, indent=2))
    TMP_FILE.replace(DATA_FILE)
    log.info("data.json written OK")


# ── Fetchers ──────────────────────────────────────────────────────────────────
TIMEOUT = 15


def fetch_floatrates():
    """USD/EGP and SAR/EGP from FloatRates (free, no auth, hourly updates)."""
    url = "https://www.floatrates.com/daily/usd.json"
    r = requests.get(url, timeout=TIMEOUT)
    r.raise_for_status()
    d = r.json()
    egp = d["egp"]["rate"]
    sar = d["sar"]["rate"]
    usd_egp = float(egp)
    # SAR is pegged to USD at 3.75 — compute cross rate
    sar_egp = usd_egp / 3.75
    log.info(f"FloatRates  USD/EGP={usd_egp:.4f}  SAR/EGP={sar_egp:.4f}")
    return usd_egp, sar_egp


def fetch_brent():
    """WTI crude from API-Ninjas (free tier). Brent is premium-only on free tier."""
    key = os.environ.get("APININJAS_KEY")
    if not key:
        raise RuntimeError("APININJAS_KEY not set")
    url = "https://api.api-ninjas.com/v1/commodityprice?name=crude_oil"
    r = requests.get(url, headers={"X-Api-Key": key}, timeout=TIMEOUT)
    r.raise_for_status()
    d = r.json()
    price = float(d["price"])
    log.info(f"API-Ninjas  WTI Crude={price:.2f}")
    return price


def fetch_gold():
    """XAU/USD from GoldAPI.io (free tier, 100 req/month → max every 6h)."""
    key = os.environ.get("GOLDAPI_KEY")
    if not key:
        raise RuntimeError("GOLDAPI_KEY not set")
    url = "https://www.goldapi.io/api/XAU/USD"
    r = requests.get(url, headers={"x-access-token": key}, timeout=TIMEOUT)
    r.raise_for_status()
    d = r.json()
    price = float(d["price"])
    log.info(f"GoldAPI     XAU/USD={price:.2f}")
    return price


# ── Modes ─────────────────────────────────────────────────────────────────────
def run_rates():
    """Fetch FX + crude. Preserve existing gold data."""
    existing = load_existing()
    errors = []

    usd_egp = sar_egp = brent = None

    try:
        usd_egp, sar_egp = fetch_floatrates()
    except Exception as e:
        errors.append(f"FloatRates: {e}")
        log.error(f"FloatRates FAILED: {e}")

    try:
        brent = fetch_brent()
    except Exception as e:
        errors.append(f"Brent: {e}")
        log.error(f"Brent FAILED: {e}")

    if usd_egp is None or brent is None:
        log.error("Fetch incomplete — data.json NOT updated")
        sys.exit(1)

    data = {
        "fetched_at":      now_iso(),
        "usd_egp":         round(usd_egp, 4),
        "sar_egp":         round(sar_egp, 4),
        "brent_usd":       round(brent, 2),
        # Preserve gold from last successful gold fetch
        "xau_usd":         existing.get("xau_usd"),
        "gold_fetched_at": existing.get("gold_fetched_at"),
    }
    save(data)


def run_gold():
    """Fetch gold only. Merge with existing data."""
    existing = load_existing()

    try:
        xau = fetch_gold()
    except Exception as e:
        log.error(f"Gold FAILED: {e} — data.json NOT updated")
        sys.exit(1)

    data = {**existing, "xau_usd": round(xau, 2), "gold_fetched_at": now_iso()}
    # If no main fetch has run yet, set a placeholder fetched_at
    data.setdefault("fetched_at", now_iso())
    save(data)


# ── Entry ─────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--gold", action="store_true", help="Fetch gold only")
    args = parser.parse_args()

    load_env()
    log.info(f"=== fetch start  mode={'gold' if args.gold else 'rates'} ===")

    try:
        if args.gold:
            run_gold()
        else:
            run_rates()
    except Exception as e:
        log.error(f"Unexpected error: {e}")
        sys.exit(1)
    finally:
        trim_log()

    log.info("=== fetch done ===")
