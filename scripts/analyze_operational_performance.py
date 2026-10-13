"""
scripts/analyze_operational_performance.py
-----------------------------------------
Extracts and computes descriptive statistics (Min, Max, Mean, Std Dev)
for Operational Performance Evaluation Results from the live system run.
"""

import os
import pymysql
import numpy as np
import datetime
from dotenv import load_dotenv

load_dotenv()

conn = pymysql.connect(
    host=os.getenv("DB_HOST", "127.0.0.1"),
    user=os.getenv("DB_USER", "root"),
    password=os.getenv("DB_PASS", ""),
    database=os.getenv("DB_NAME", "crosswalk_db"),
    cursorclass=pymysql.cursors.DictCursor
)

with conn.cursor() as cur:
    # 1. Fetch events from today's active session (October 13, 2026)
    cur.execute("""
        SELECT * FROM events 
        WHERE timestamp_iso >= '2026-10-13 00:00:00'
        ORDER BY id ASC
    """)
    rows_today = cur.fetchall()
    
    print(f"Total events recorded today (2026-10-13): {len(rows_today)}")
    print("First 10 latencies:", [r["latency_ms"] for r in rows_today[:10]])
    print("Max latency event:", max(rows_today, key=lambda r: r["latency_ms"]))

def parse_iso(ts_str):
    if not ts_str:
        return None
    try:
        # e.g. 2026-10-13T00:09:39.852Z
        cleaned = ts_str.replace("Z", "")
        return datetime.datetime.fromisoformat(cleaned)
    except Exception:
        return None

def analyze_dataset(rows, label="Session"):
    print("=" * 65)
    print(f"ANALYSIS FOR: {label} ({len(rows)} samples)")
    print("=" * 65)
    
    # 1. Frame Processing Time (latency_ms recorded by YOLO)
    latencies = [r["latency_ms"] for r in rows if r["latency_ms"] > 0]
    
    # 2. Warning Activation Latency (ms):
    # Calculated from capture_ts -> warning_ts (total e2e time to warning decision)
    # Also check warning-active frames (warning_device_on == 1)
    e2e_latencies = []
    e2e_warn_only = []
    
    for r in rows:
        c_ts = parse_iso(r.get("capture_ts"))
        w_ts = parse_iso(r.get("warning_ts"))
        if c_ts and w_ts:
            delta_ms = (w_ts - c_ts).total_seconds() * 1000.0
            if delta_ms >= 0:
                e2e_latencies.append(delta_ms)
                if r["warning_device_on"] == 1:
                    e2e_warn_only.append(delta_ms)
                    
    # 3. Processing Speed (FPS):
    # FPS can be computed instantaneously per frame as 1000 / latency_ms
    # or from time delta between consecutive frame timestamps
    fps_instant = [1000.0 / l for l in latencies if l > 0]
    
    consec_fps = []
    for i in range(1, len(rows)):
        t1 = rows[i-1]["timestamp_iso"]
        t2 = rows[i]["timestamp_iso"]
        if isinstance(t1, datetime.datetime) and isinstance(t2, datetime.datetime):
            dt = (t2 - t1).total_seconds()
            if 0.01 < dt < 2.0:
                consec_fps.append(1.0 / dt)

    def stats(arr, name):
        if not arr:
            print(f"{name}: NO DATA")
            return
        a = np.array(arr)
        print(f"{name}:")
        print(f"  Count: {len(a)}")
        print(f"  Min:   {np.min(a):.2f}")
        print(f"  Max:   {np.max(a):.2f}")
        print(f"  Mean:  {np.mean(a):.2f}")
        print(f"  Std:   {np.std(a, ddof=1):.2f}")

    stats(latencies, "1. Frame Processing Time (YOLO latency_ms)")
    stats(e2e_latencies, "2. Total Pipeline / Warning Decision Latency (capture_ts to warning_ts)")
    stats(e2e_warn_only, "2b. Warning Activation Latency (when warning_device_on=1)")
    stats(fps_instant, "3a. Processing Speed (Instantaneous FPS = 1000/lat)")
    stats(consec_fps, "3b. Processing Speed (Throughput FPS from consecutive frames)")
    
    # Check warning transitions
    warn_transitions = []
    for i in range(1, len(rows)):
        if rows[i]["warning_device_on"] == 1 and rows[i-1]["warning_device_on"] == 0:
            c_ts = parse_iso(rows[i].get("capture_ts"))
            w_ts = parse_iso(rows[i].get("warning_ts"))
            if c_ts and w_ts:
                warn_transitions.append((w_ts - c_ts).total_seconds() * 1000.0)
    if warn_transitions:
        stats(warn_transitions, "2c. Warning Activation Latency (At the Exact Moment Warning Turns ON 0->1)")

analyze_dataset(rows_today, "TODAY'S ACTIVE RUN (Raw Logged — All 150 Frames)")

# Filter out the single 3.5s background system interrupt to show normal steady-state operation
steady_state_rows = [r for r in rows_today if r["latency_ms"] < 500]
analyze_dataset(steady_state_rows, "TODAY'S ACTIVE RUN (Steady-State Continuous Operation — Outlier Removed)")
