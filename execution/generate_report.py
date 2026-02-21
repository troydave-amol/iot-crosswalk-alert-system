"""
execution/generate_report.py
----------------------------
Queries the MySQL events table for a given time range and writes
a summary CSV report to reports/.

Usage:
    python execution/generate_report.py --range today
    python execution/generate_report.py --range all --out reports/custom_report.csv

Output columns:
    timestamp_iso, warning_device_on, child_in_roi, confidence, latency_ms

Summary printed to console:
    total_events, total_warnings, total_detections, avg_latency_ms, peak_hour
"""

import argparse
import csv
import datetime
import os
import sys
from pathlib import Path
from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent.parent / ".env")

try:
    import mysql.connector
except ImportError:
    print("ERROR: mysql-connector-python not installed. Run: pip install mysql-connector-python")
    sys.exit(1)

PROJECT_ROOT = Path(__file__).resolve().parent.parent
REPORTS_DIR  = PROJECT_ROOT / "reports"

DB_HOST     = os.getenv("DB_HOST", "localhost")
DB_PORT     = int(os.getenv("DB_PORT", "3306"))
DB_USER     = os.getenv("DB_USER", "root")
DB_PASSWORD = os.getenv("DB_PASSWORD", "")
DB_NAME     = os.getenv("DB_NAME", "crosswalk_db")


def range_to_utc_start(range_str: str) -> datetime.datetime | None:
    now = datetime.datetime.utcnow()
    if range_str == "15m":
        return now - datetime.timedelta(minutes=15)
    if range_str == "1h":
        return now - datetime.timedelta(hours=1)
    if range_str == "today":
        local_now = now + datetime.timedelta(hours=8)
        local_midnight = local_now.replace(hour=0, minute=0, second=0, microsecond=0)
        return local_midnight - datetime.timedelta(hours=8)
    if range_str == "all":
        return None
    raise ValueError(f"Unknown range: {range_str}")


def fetch_events(range_str: str) -> list[dict]:
    start = range_to_utc_start(range_str)
    conn  = mysql.connector.connect(
        host=DB_HOST, port=DB_PORT,
        user=DB_USER, password=DB_PASSWORD,
        database=DB_NAME
    )
    cursor = conn.cursor(dictionary=True)
    if start:
        cursor.execute(
            "SELECT timestamp_iso, warning_device_on, child_in_roi, confidence, latency_ms "
            "FROM events WHERE created_at >= %s ORDER BY created_at ASC",
            (start,)
        )
    else:
        cursor.execute(
            "SELECT timestamp_iso, warning_device_on, child_in_roi, confidence, latency_ms "
            "FROM events ORDER BY created_at ASC"
        )
    rows = cursor.fetchall()
    cursor.close()
    conn.close()
    return rows


def compute_summary(rows: list[dict]) -> dict:
    if not rows:
        return {
            "total_events": 0,
            "total_warnings": 0,
            "total_detections": 0,
            "avg_latency_ms": 0.0,
            "peak_hour": "N/A",
        }

    total_warnings   = sum(1 for r in rows if r["warning_device_on"])
    total_detections = sum(1 for r in rows if r["child_in_roi"])
    latencies        = [r["latency_ms"] for r in rows if r["latency_ms"] is not None]
    avg_latency      = round(sum(latencies) / len(latencies), 2) if latencies else 0.0

    # Peak hour (Asia/Manila local time)
    hour_counts: dict[int, int] = {}
    for r in rows:
        try:
            ts = datetime.datetime.fromisoformat(str(r["timestamp_iso"]).replace("Z", "+00:00"))
            local_ts = ts + datetime.timedelta(hours=8)
            hour_counts[local_ts.hour] = hour_counts.get(local_ts.hour, 0) + 1
        except Exception:
            pass
    peak_hour = f"{max(hour_counts, key=hour_counts.get):02d}:00" if hour_counts else "N/A"

    return {
        "total_events":     len(rows),
        "total_warnings":   total_warnings,
        "total_detections": total_detections,
        "avg_latency_ms":   avg_latency,
        "peak_hour":        peak_hour,
    }


def main():
    parser = argparse.ArgumentParser(description="Generate a CSV report from MySQL events.")
    parser.add_argument("--range", required=True, choices=["15m", "1h", "today", "all"],
                        help="Time range for the report")
    parser.add_argument("--out", default=None, help="Output CSV path (default: reports/<range>_report.csv)")
    args = parser.parse_args()

    REPORTS_DIR.mkdir(exist_ok=True)
    out_path = Path(args.out) if args.out else REPORTS_DIR / f"{args.range}_report.csv"

    print(f"Fetching events for range: {args.range}")
    try:
        rows = fetch_events(args.range)
    except Exception as e:
        print(f"❌ DB error: {e}")
        sys.exit(1)

    # Write CSV
    fieldnames = ["timestamp_iso", "warning_device_on", "child_in_roi", "confidence", "latency_ms"]
    with open(out_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)

    summary = compute_summary(rows)
    print(f"\nSummary (range={args.range}):")
    for k, v in summary.items():
        print(f"  {k}: {v}")
    print(f"\n✅ Report saved to: {out_path}")


if __name__ == "__main__":
    main()
