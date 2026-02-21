#!/usr/bin/env python3
"""
API Smoke Test for Smart Crosswalk Dashboard
Tests /api/health, /api/events, and /api/analytics endpoints.

Usage:
    python scripts/smoke_test_api.py
    python scripts/smoke_test_api.py --host http://localhost:5000
"""

import sys
import json
import argparse
import urllib.request
import urllib.error
from datetime import datetime, timezone

DEFAULT_HOST = "http://localhost:5000"
RANGES = ["15m", "1h", "today", "all"]


def get(host, path):
    url = f"{host}{path}"
    try:
        with urllib.request.urlopen(url, timeout=5) as resp:
            return resp.status, json.loads(resp.read())
    except urllib.error.HTTPError as e:
        return e.code, {}
    except Exception as e:
        return None, str(e)


def check_health(host):
    print("\n[1] GET /api/health")
    status, body = get(host, "/api/health")
    if status == 200 and body.get("ok") is True:
        print("  PASS - health ok")
        return True
    else:
        print(f"  FAIL - status={status} body={body}")
        return False


def check_events(host):
    print("\n[2] GET /api/events (range checks)")
    totals = {}
    all_pass = True
    for r in RANGES:
        status, body = get(host, f"/api/events?range={r}&per_page=1")
        if status == 200 and "total" in body:
            totals[r] = body["total"]
            print(f"  range={r:6s} total={totals[r]}")
        else:
            print(f"  FAIL - range={r} status={status}")
            all_pass = False

    # Validate subset invariant: 15m <= 1h <= today <= all
    if all(r in totals for r in RANGES):
        if totals["15m"] <= totals["1h"] <= totals["today"] <= totals["all"]:
            print("  PASS - range subset invariant holds")
        else:
            print(f"  FAIL - range invariant violated: {totals}")
            all_pass = False

    return all_pass


def check_analytics(host):
    print("\n[3] GET /api/analytics (required fields)")
    required_fields = ["range_start", "range_end", "timezone", "bin_unit",
                       "total_warnings", "total_detections"]
    all_pass = True
    for r in RANGES:
        status, body = get(host, f"/api/analytics?range={r}")
        if status == 200:
            missing = [f for f in required_fields if f not in body]
            if missing:
                print(f"  FAIL - range={r} missing fields: {missing}")
                all_pass = False
            else:
                print(f"  PASS - range={r}")
        else:
            print(f"  FAIL - range={r} status={status}")
            all_pass = False
    return all_pass


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default=DEFAULT_HOST)
    args = parser.parse_args()

    print(f"Smart Crosswalk API Smoke Test")
    print(f"Host: {args.host}")
    print(f"Time: {datetime.now(timezone.utc).isoformat()}")

    results = [
        check_health(args.host),
        check_events(args.host),
        check_analytics(args.host),
    ]

    passed = sum(results)
    total = len(results)
    print(f"\n{'='*40}")
    print(f"Result: {passed}/{total} checks passed")

    sys.exit(0 if all(results) else 1)


if __name__ == "__main__":
    main()
