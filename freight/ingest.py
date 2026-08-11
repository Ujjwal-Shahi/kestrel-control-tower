"""
Walks the mock Kestrel Logistics Partner API's /v1/freight_invoices cursor,
handling its documented chaos (~11% 429, ~4% 503, slow first page), and
writes freight/cache/invoices.csv for the dashboard.

If the API is unreachable at all, falls back to whatever is already cached
(a stale number beats a crashed dashboard) and says so loudly.

Run: python -m freight.ingest
Requires: partner_api/server.py running locally (python partner_api/server.py)
"""
import os
import sys
import time
import datetime as dt

import requests
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import config

HEADERS = {"X-API-Key": config.FREIGHT_API_KEY}
MAX_RETRIES = 5
REQUEST_TIMEOUT = 15


def request_with_backoff(session, url, params=None):
    for attempt in range(MAX_RETRIES):
        try:
            r = session.get(url, headers=HEADERS, params=params, timeout=REQUEST_TIMEOUT)
        except requests.RequestException as e:
            wait = 2 ** attempt
            print(f"  network error ({e}), retry in {wait}s")
            time.sleep(wait)
            continue
        if r.status_code == 429:
            wait = int(r.headers.get("Retry-After", 2 ** attempt))
            print(f"  429, honoring Retry-After={wait}s")
            time.sleep(wait)
            continue
        if r.status_code == 503:
            wait = 2 ** attempt
            print(f"  503, backoff {wait}s")
            time.sleep(wait)
            continue
        r.raise_for_status()
        return r
    raise RuntimeError(f"gave up after {MAX_RETRIES} retries: {url}")


def walk_invoices(session, date_from=None, date_to=None):
    cursor = None
    rows = []
    page = 0
    while True:
        params = {}
        if cursor:
            params["cursor"] = cursor
        if date_from:
            params["from"] = date_from
        if date_to:
            params["to"] = date_to
        r = request_with_backoff(session, f"{config.FREIGHT_API_BASE}/v1/freight_invoices", params)
        body = r.json()
        rows.extend(body["data"])
        page += 1
        if page % 20 == 0:
            print(f"  ...{len(rows)} invoices so far")
        cursor = body.get("next_cursor")
        if not cursor:
            break
    return rows


def to_ist(utc_str):
    if not utc_str:
        return None
    ts = pd.to_datetime(utc_str, utc=True)
    return ts.tz_convert("Asia/Kolkata").tz_localize(None)


def main():
    session = requests.Session()
    try:
        health = session.get(f"{config.FREIGHT_API_BASE}/v1/health", timeout=5)
        health.raise_for_status()
    except requests.RequestException as e:
        print(f"Freight API unreachable ({e}).")
        if os.path.exists(config.FREIGHT_CACHE_PATH):
            print(f"Keeping existing cache at {config.FREIGHT_CACHE_PATH} -- dashboard will use stale data.")
        else:
            print("No cache exists either -- freight cost metrics will be empty until this is run "
                  "with the API reachable.")
        return

    print("Walking /v1/freight_invoices ...")
    raw = walk_invoices(session)
    df = pd.DataFrame(raw)
    df["amount_inr"] = df["amount"] / 100.0
    df["detention_charge_inr"] = df["detention_charge"] / 100.0
    df["created_at_ist"] = df["created_at_utc"].apply(to_ist)

    os.makedirs(os.path.dirname(config.FREIGHT_CACHE_PATH), exist_ok=True)
    df.to_csv(config.FREIGHT_CACHE_PATH, index=False)
    print(f"Wrote {len(df)} invoices -> {config.FREIGHT_CACHE_PATH}")


if __name__ == "__main__":
    main()
