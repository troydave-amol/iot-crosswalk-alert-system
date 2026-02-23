"""
scripts/verify_db.py
----------------------
Runs raw SQL ground-truth queries for each time range and compares
results against the /api/analytics endpoint.

Any mismatch is treated as a BUG.

Usage:
    python scripts/verify_db.py
    python scripts/verify_db.py --host localhost --port 5000

Prerequisites:
    - Flask app must be running (python app.py)
    - MySQL must be accessible with credentials from .env
    - pip install python-dotenv mysql-connector-python requests
"""

import os
import sys
import datetime
import requests
from pathlib import Path
from dotenv import load_dotenv

# Load .env from project root
load_dotenv(Path(__file__).resolve().parent.parent / ".env")

try:
    import mysql.connector
except ImportError:
    print("ERROR: mysql-connector-python not installed. Run: pip install mysql-connector-python")
    sys.exit(1)

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
DB_HOST     = os.getenv("DB_HOST", "localhost")
DB_PORT     = int(os.getenv("DB_PORT", "3306"))
DB_USER     = os.getenv("DB_USER", "root")
DB_PASSWORD = os.getenv("DB_PASSWORD", "")
DB_NAME     = os.getenv("DB_NAME", "crosswalk_db")

API_HOST    = os.getenv("API_HOST", "localhost")
API_PORT    = int(os.getenv("API_PORT", "5000"))
API_BASE    = f"http://{API_HOST}:{API_PORT}"

RANGES = ["15m", "1h", "today", "all"]


def get_db_connection():
    return mysql.connector.connect(
        host=DB_HOST, port=DB_PORT,
        user=DB_USER, password=DB_PASSWORD,
        database=DB_NAME
    )


def range_to_utc_start(range_str: str) -> datetime.datetime | None:
    """Return UTC datetime for range start, or None for 'all'."""
    now = datetime.datetime.utcnow()
    if range_str == "15m":
        return now - datetime.timedelta(minutes=15)
    if range_str == "1h":
        return now - datetime.timedelta(hours=1)
    if range_str == "today":
        # midnight Asia/Manila = UTC-8 offset → UTC midnight = local midnight + 8h
        # Use a simple approach: today local midnight in UTC
        local_now = now + datetime.timedelta(hours=8)
        local_midnight = local_now.replace(hour=0, minute=0, second=0, microsecond=0)
        return local_midnight - datetime.timedelta(hours=8)
    if range_str == "all":
        return None
    raise ValueError(f"Unknown range: {range_str}")


def sql_ground_truth(conn, range_str: str) -> dict:
    """Run raw SQL and return ground-truth counts."""
    start = range_to_utc_start(range_str)
    cursor = conn.cursor(dictionary=True)

    if start:
        where = "WHERE created_at >= %s"
        params = (start,)
    else:
        where = ""
        params = ()

    cursor.execute(f"SELECT COUNT(*) AS total_events FROM events {where}", params)
    total_events = cursor.fetchone()["total_events"]

    cursor.execute(f"SELECT COUNT(*) AS total_warnings FROM events {where} {'AND' if where else 'WHERE'} warning_device_on = 1",
                   params)
    total_warnings = cursor.fetchone()["total_warnings"]

    cursor.execute(f"SELECT COUNT(*) AS total_detections FROM events {where} {'AND' if where else 'WHERE'} child_in_roi = 1",
                   params)
    total_detections = cursor.fetchone()["total_detections"]

    cursor.execute(f"SELECT COALESCE(AVG(latency_ms), 0) AS avg_latency FROM events {where}", params)
    avg_latency = float(cursor.fetchone()["avg_latency"])

    cursor.close()
    return {
        "total_events":     total_events,
        "total_warnings":   total_warnings,
        "total_detections": total_detections,
        "avg_latency_ms":   round(avg_latency, 2),
    }


def api_ground_truth(range_str: str) -> dict | None:
    """Call /api/analytics and return relevant fields, or None on failure."""
    try:
        resp = requests.get(f"{API_BASE}/api/analytics", params={"range": range_str}, timeout=5)
        if resp.status_code != 200:
            print(f"  ⚠️  API returned HTTP {resp.status_code} for range={range_str}")
            return None
        data = resp.json()
        return {
            "total_events":     data.get("total_events", -1),
            "total_warnings":   data.get("total_warnings", -1),
            "total_detections": data.get("total_detections", -1),
            "avg_latency_ms":   data.get("avg_latency_ms", -1),
        }
    except requests.RequestException as e:
        print(f"  ❌ API request failed for range={range_str}: {e}")
        return None


def main():
    print("=" * 60)
    print("DB vs API Analytics Ground Truth Verification")
    print("=" * 60)

    try:
        conn = get_db_connection()
        print("✅ DB connection OK\n")
    except Exception as e:
        print(f"❌ DB connection failed: {e}")
        sys.exit(1)

    all_pass = True
    for range_str in RANGES:
        print(f"--- Range: {range_str} ---")
        sql_truth = sql_ground_truth(conn, range_str)
        api_truth = api_ground_truth(range_str)

        if api_truth is None:
            all_pass = False
            continue

        fields = ["total_events", "total_warnings", "total_detections"]
        for field in fields:
            sql_val = sql_truth[field]
            api_val = api_truth[field]
            match = "✅" if sql_val == api_val else "❌ MISMATCH"
            print(f"  {match}  {field}: SQL={sql_val}  API={api_val}")
            if sql_val != api_val:
                all_pass = False

        print()

    conn.close()

    print("=" * 60)
    if all_pass:
        print("✅ ALL CHECKS PASSED — DB and API are consistent.")
    else:
        print("❌ MISMATCHES FOUND — treat as bugs until resolved.")
        sys.exit(1)


if __name__ == "__main__":
    main()
