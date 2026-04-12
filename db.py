import os
import pymysql
import pymysql.cursors
from datetime import datetime, timezone, timedelta
from dotenv import load_dotenv

load_dotenv()

def get_connection():
    """
    Creates a new database connection.
    Intentionally determines database presence to allow creation if missing.
    """
    return pymysql.connect(
        host=os.getenv("DB_HOST", "localhost"),
        user=os.getenv("DB_USER", "root"),
        password=os.getenv("DB_PASS", ""),
        # We don't specify database here initially to allow 'CREATE DATABASE' command
        # or we specify it if we are sure it exists. 
        # Strategy: Connect without DB first to ensure it exists, then connect with DB.
        # However, for simplicity and standard usage, we usually connect with DB.
        # Given the requirement to generic "init_db", we will handle the DB selection dynamically.
        charset='utf8mb4',
        cursorclass=pymysql.cursors.DictCursor,
        autocommit=True
    )

def init_db():
    """
    Initializes the database and table.
    Safe to run multiple times.
    """
    conn = None
    try:
        # 1. Connect without selecting a database to create it if needed
        conn = pymysql.connect(
            host=os.getenv("DB_HOST", "localhost"),
            user=os.getenv("DB_USER", "root"),
            password=os.getenv("DB_PASS", ""),
            charset='utf8mb4',
            cursorclass=pymysql.cursors.DictCursor,
            autocommit=True
        )
        target_db = os.getenv("DB_NAME", "crosswalk_db")
        
        with conn.cursor() as cursor:
            # Create Database
            cursor.execute(f"CREATE DATABASE IF NOT EXISTS {target_db}")
            cursor.execute(f"USE {target_db}")
            
            # Create Table
            create_table_sql = """
            CREATE TABLE IF NOT EXISTS events (
                id INT AUTO_INCREMENT PRIMARY KEY,
                timestamp_iso DATETIME NOT NULL,
                source VARCHAR(16) NOT NULL,
                child_in_roi TINYINT(1) NOT NULL,
                roi_status VARCHAR(16) NOT NULL,
                confidence FLOAT NOT NULL,
                latency_ms INT NOT NULL,
                warning_logic_on TINYINT(1) NOT NULL,
                switch_enabled TINYINT(1) NOT NULL,
                warning_device_on TINYINT(1) NOT NULL,
                battery_percent FLOAT NOT NULL,
                solar_status VARCHAR(16) NOT NULL,
                scenario VARCHAR(32) NULL,
                camera_status VARCHAR(16) NULL,
                edge_status VARCHAR(16) NULL,
                led_driver_status VARCHAR(16) NULL,
                INDEX idx_timestamp (timestamp_iso),
                INDEX idx_warning (warning_device_on),
                INDEX idx_child (child_in_roi)
            )
            """
            cursor.execute(create_table_sql)

            # Attempt to add indexes individually if table already existed without them
            # This handles the migration case where the table exists but new indexes don't
            try:
                cursor.execute("CREATE INDEX idx_warning ON events (warning_device_on)")
            except Exception:
                pass # Index likely exists or other non-critical error

            try:
                cursor.execute("CREATE INDEX idx_child ON events (child_in_roi)")
            except Exception:
                pass

            # Migration: add child_count column if it doesn't exist (safe for existing tables)
            try:
                cursor.execute("ALTER TABLE events ADD COLUMN child_count INT NOT NULL DEFAULT 0")
                print(f"  → Added 'child_count' column to events table.")
            except Exception:
                pass  # Column already exists

            print(f"Database '{target_db}' and table 'events' checked/initialized successfully.")
            
    except Exception as e:
        print(f"DB INIT INVALID: {e}")
        # We do not raise, so the app can continue running even if DB fails
    finally:
        if conn:
            conn.close()

def insert_event(payload):
    """
    Inserts a status update event into the database.
    Provides defaults for power/derived fields that may not exist in live inference payloads.
    """
    conn = None
    try:
        # Core required fields — these MUST exist
        core_keys = [
            "timestamp_iso", "source", "child_in_roi", "roi_status",
            "confidence", "latency_ms", "warning_device_on"
        ]
        for key in core_keys:
            if key not in payload:
                print(f"DB INSERT FAILED: Missing key {key}")
                return

        # Derived / optional fields — provide defaults if missing
        payload.setdefault("warning_logic_on", payload["child_in_roi"])
        payload.setdefault("switch_enabled", True)
        payload.setdefault("battery_percent", 0.0)
        payload.setdefault("solar_status", "N/A")
        payload["roi_status"] = "CHILD_IN_ROI" if int(payload["child_in_roi"]) == 1 else "CLEAR"

        # Connect specifically to the database now
        conn = pymysql.connect(
            host=os.getenv("DB_HOST", "localhost"),
            user=os.getenv("DB_USER", "root"),
            password=os.getenv("DB_PASS", ""),
            database=os.getenv("DB_NAME", "crosswalk_db"),
            charset='utf8mb4',
            cursorclass=pymysql.cursors.DictCursor,
            autocommit=True
        )

        with conn.cursor() as cursor:
            sql = """
            INSERT INTO events (
                timestamp_iso, source, child_in_roi, roi_status, confidence, latency_ms,
                warning_logic_on, switch_enabled, warning_device_on, child_count,
                battery_percent, solar_status,
                scenario, camera_status, edge_status, led_driver_status
            ) VALUES (
                %s, %s, %s, %s, %s, %s,
                %s, %s, %s, %s,
                %s, %s,
                %s, %s, %s, %s
            )
            """
            
            # Parse ISO timestamp to MySQL DATETIME
            # Handle potential "Z" or other ISO variants
            ts_str = payload["timestamp_iso"].replace("Z", "")
            # Truncate microseconds if present for safer MySQL compatibility unless fractional seconds are enabled in DB
            # MySQL 5.6+ supports fractional seconds but often defaults to second precision.
            # We'll just pass the string, MySQL driver usually handles ISO format well, 
            # but explicit parsing is safer for strict DATETIME columns.
            try:
                # Attempt to parse if it contains T
                if "T" in ts_str:
                    dt_obj = datetime.fromisoformat(ts_str)
                    ts_val = dt_obj.strftime("%Y-%m-%d %H:%M:%S")
                else:
                    ts_val = ts_str
            except ValueError:
                ts_val = ts_str # Fallback to original string

            values = (
                ts_val,
                payload["source"],
                int(payload["child_in_roi"]),
                payload["roi_status"],
                payload["confidence"],
                payload["latency_ms"],
                int(payload["warning_logic_on"]),
                int(payload["switch_enabled"]),
                int(payload["warning_device_on"]),
                int(payload.get("child_count", 0)),
                payload["battery_percent"],
                payload["solar_status"],
                payload.get("scenario"),
                payload.get("camera_status"),
                payload.get("edge_status"),
                payload.get("led_driver_status")
            )
            
            cursor.execute(sql, values)
            print(f"DB INSERT OK: {ts_val} warning_device_on={int(payload['warning_device_on'])} child_in_roi={int(payload['child_in_roi'])} child_count={int(payload.get('child_count', 0))}")

    except Exception as e:
        print(f"DB INSERT FAILED: {e}")
    finally:
        if conn:
            conn.close()

def fetch_events(
    limit=50, 
    offset=0, 
    time_range="all", 
    warning_only=False, 
    in_roi_only=False, 
    min_conf=0.0, 
    scenario=None, 
    search=None
):
    """
    Fetches events from the database with filtering and pagination.
    Returns strings/floats/ints (JSON safe).
    Raises exception on DB error.
    """
    conn = None
    try:
        # Connect to DB
        conn = pymysql.connect(
            host=os.getenv("DB_HOST", "localhost"),
            user=os.getenv("DB_USER", "root"),
            password=os.getenv("DB_PASS", ""),
            database=os.getenv("DB_NAME", "crosswalk_db"),
            charset='utf8mb4',
            cursorclass=pymysql.cursors.DictCursor
        )

        # Dynamic time-based scenario label (same logic as analytics chart)
        manila_t = "TIME(DATE_ADD(timestamp_iso, INTERVAL 8 HOUR))"
        scenario_case = f"""CASE
            WHEN {manila_t} >= '06:00:00' AND {manila_t} < '08:30:00' THEN 'Morning School Entry'
            WHEN {manila_t} >= '11:00:00' AND {manila_t} < '13:30:00' THEN 'Mid-Day Shift'
            WHEN {manila_t} >= '15:30:00' AND {manila_t} < '17:00:00' THEN 'Afternoon Dismissal'
            ELSE 'Standard Daylight Ops'
        END"""

        # Build WHERE clause
        conditions = []
        params = []

        # 1. Time Range — use UTC_TIMESTAMP() to match UTC-stored timestamps
        if time_range == "15m":
            conditions.append("timestamp_iso >= DATE_SUB(UTC_TIMESTAMP(), INTERVAL 15 MINUTE)")
        elif time_range == "1h":
            conditions.append("timestamp_iso >= DATE_SUB(UTC_TIMESTAMP(), INTERVAL 1 HOUR)")
        elif time_range == "today":
            # "Today" = midnight Asia/Manila (UTC+8), converted to UTC for comparison
            manila_tz = timezone(timedelta(hours=8))
            manila_now = datetime.now(manila_tz)
            manila_today_start = manila_now.replace(hour=0, minute=0, second=0, microsecond=0)
            today_utc = manila_today_start.astimezone(timezone.utc)
            conditions.append("timestamp_iso >= %s")
            params.append(today_utc.strftime("%Y-%m-%d %H:%M:%S"))
        # "all" adds no condition

        # 2. Boolean Flags
        if warning_only:
            conditions.append("warning_device_on = 1")
        
        if in_roi_only:
            conditions.append("child_in_roi = 1")

        # 3. Minimum Confidence
        if min_conf > 0:
            conditions.append("confidence >= %s")
            params.append(min_conf)

        # 4. Scenario (Exact Match against computed time-based label)
        if scenario:
            conditions.append(f"{scenario_case} = %s")
            params.append(scenario)

        # 5. Search (Flexible — includes computed scenario label + Manila timestamp)
        if search:
            manila_ts = "DATE_FORMAT(DATE_ADD(timestamp_iso, INTERVAL 8 HOUR), '%%Y-%%m-%%d %%h:%%i:%%s %%p')"
            search_clause = (
                f"(source LIKE %s OR {scenario_case} LIKE %s"
                f" OR roi_status LIKE %s OR {manila_ts} LIKE %s)"
            )
            conditions.append(search_clause)
            search_pattern = f"%{search}%"
            params.extend([search_pattern, search_pattern, search_pattern, search_pattern])

        where_sql = ""
        if conditions:
            where_sql = "WHERE " + " AND ".join(conditions)

        with conn.cursor() as cursor:
            # A. Get Total Count (for pagination)
            count_sql = f"SELECT COUNT(*) as total FROM events {where_sql}"
            cursor.execute(count_sql, params)
            total_rows = cursor.fetchone()["total"]

            # B. Fetch Data
            # Explicit columns — scenario is dynamically computed from timestamp
            fields = [
                "id", "timestamp_iso", "source", "child_in_roi", "roi_status", 
                "confidence", "latency_ms", "warning_logic_on", "switch_enabled", 
                "warning_device_on", "battery_percent", "solar_status", 
                f"{scenario_case} AS scenario",
                "camera_status", "edge_status", "led_driver_status"
            ]
            fields_str = ", ".join(fields)
            
            # Order by newest first
            query_sql = f"""
                SELECT {fields_str} 
                FROM events 
                {where_sql} 
                ORDER BY id DESC 
                LIMIT %s OFFSET %s
            """
            # Add limit/offset to params
            query_params = params + [limit, offset]
            
            cursor.execute(query_sql, query_params)
            rows = cursor.fetchall()
            
            # Serialize for JSON
            serialized_rows = []
            for row in rows:
                new_row = row.copy()
                
                # datetime -> ISO string
                if isinstance(new_row["timestamp_iso"], datetime):
                    new_row["timestamp_iso"] = new_row["timestamp_iso"].strftime("%Y-%m-%dT%H:%M:%SZ")
                elif isinstance(new_row["timestamp_iso"], str):
                    # Ensure string format is also strict ISO with Z
                    # Typical MySQL string: "2023-10-27 10:00:00"
                    if " " in new_row["timestamp_iso"] and "T" not in new_row["timestamp_iso"]:
                        new_row["timestamp_iso"] = new_row["timestamp_iso"].replace(" ", "T")
                    
                    if not new_row["timestamp_iso"].endswith("Z"):
                         new_row["timestamp_iso"] += "Z"
                
                # Decimal -> float (if using Decimal cursor, but here using standard float in table)
                # Just in case pymysql returns Decimal for FLOAT columns sometimes
                for k, v in new_row.items():
                    if hasattr(v, 'quantize'): # Check for Decimal-like
                         new_row[k] = float(v)

                serialized_rows.append(new_row)

            return {
                "total": total_rows,
                "rows": serialized_rows
            }

    except Exception as e:
        print(f"DB FETCH ERROR: {e}")
        raise e # Re-raise to let caller handle 503
    finally:
        if conn:
            conn.close()


def fetch_analytics_aggregates(time_range="all"):
    """
    Returns server-side computed analytics aggregates for a given time range.
    ALL matching rows are processed in SQL — never bounded by a page limit.
    Timezone: 'today' uses Asia/Manila (UTC+8) midnight; rolling ranges use UTC.
    Raises exception on DB error so caller can return 503.
    """
    conn = None
    try:
        conn = pymysql.connect(
            host=os.getenv("DB_HOST", "localhost"),
            user=os.getenv("DB_USER", "root"),
            password=os.getenv("DB_PASS", ""),
            database=os.getenv("DB_NAME", "crosswalk_db"),
            charset='utf8mb4',
            cursorclass=pymysql.cursors.DictCursor
        )

        # Fix: enforce UTC session timezone so UNIX_TIMESTAMP() / HOUR() / DATE() binning
        # is always UTC-relative, regardless of the MySQL server's global timezone setting.
        with conn.cursor() as _tz_cursor:
            _tz_cursor.execute("SET time_zone = '+00:00'")

        # ── Range → SQL condition ────────────────────────────────────────────────
        conditions = []
        params = []
        now_utc = datetime.now(timezone.utc)
        manila_tz = timezone(timedelta(hours=8))

        if time_range == "15m":
            range_start_utc = now_utc - timedelta(minutes=15)
            conditions.append("timestamp_iso >= %s")
            params.append(range_start_utc.strftime("%Y-%m-%d %H:%M:%S"))
            bin_seconds = 60       # 1-minute bins
            bin_unit = "1m"

        elif time_range == "1h":
            range_start_utc = now_utc - timedelta(hours=1)
            conditions.append("timestamp_iso >= %s")
            params.append(range_start_utc.strftime("%Y-%m-%d %H:%M:%S"))
            bin_seconds = 300      # 5-minute bins
            bin_unit = "5m"

        elif time_range == "today":
            # Midnight Asia/Manila → convert to UTC for comparison against UTC-stored values
            manila_now = datetime.now(manila_tz)
            manila_today_start = manila_now.replace(hour=0, minute=0, second=0, microsecond=0)
            range_start_utc = manila_today_start.astimezone(timezone.utc)
            conditions.append("timestamp_iso >= %s")
            params.append(range_start_utc.strftime("%Y-%m-%d %H:%M:%S"))
            bin_seconds = 3600     # 1-hour bins
            bin_unit = "1h"

        else:  # "all"
            range_start_utc = None
            bin_seconds = 86400    # 1-day bins
            bin_unit = "1d"

        # Freeze range_end once so every query in this request sees the same closed window.
        # Without this, each of the 5 queries could read different totals as new rows are inserted.
        range_end_utc = now_utc
        range_end_str = range_end_utc.strftime("%Y-%m-%d %H:%M:%S")
        conditions.append("timestamp_iso < %s")
        params.append(range_end_str)
        where_sql = "WHERE " + " AND ".join(conditions)

        with conn.cursor() as cursor:

            # ══════════════════════════════════════════════════════════════════
            # 3-STEP CTE PIPELINE  (Gaps-and-Islands for session counting)
            # ──────────────────────────────────────────────────────────────────
            # Step 1 — flags:   LAG() over entire table for 0→1 transitions
            # Step 2 — sessions: rolling SUM(detect_start) to assign session IDs
            # Step 3 — enriched: MAX(child_count) per detect session, attached
            #                    to every row so outer queries can filter by time
            #
            # Key column:
            #   session_max_children = the peak child_count within each session.
            #   Only read at detect_start=1 rows for aggregation to avoid
            #   double-counting.
            # ══════════════════════════════════════════════════════════════════
            cte_base = """
                WITH flags AS (
                    SELECT
                        id, timestamp_iso, latency_ms,
                        warning_device_on, child_in_roi, child_count, confidence, scenario,
                        CASE WHEN warning_device_on = 1
                             AND COALESCE(LAG(warning_device_on) OVER (ORDER BY id), 0) = 0
                             THEN 1 ELSE 0 END  AS warn_start,
                        CASE WHEN child_in_roi = 1
                             AND COALESCE(LAG(child_in_roi) OVER (ORDER BY id), 0) = 0
                             THEN 1 ELSE 0 END  AS detect_start,
                        CASE WHEN warning_device_on = 1
                             AND child_in_roi = 0
                             AND COALESCE(LAG(warning_device_on) OVER (ORDER BY id), 0) = 0
                             THEN 1 ELSE 0 END  AS false_warn_start
                    FROM events
                ),
                sessions AS (
                    SELECT
                        f.*,
                        SUM(detect_start) OVER (ORDER BY id) AS detect_session_id
                    FROM flags f
                ),
                enriched AS (
                    SELECT
                        s.*,
                        CASE WHEN detect_session_id > 0
                             THEN MAX(child_count) OVER (PARTITION BY detect_session_id)
                             ELSE 0 END AS session_max_children
                    FROM sessions s
                )
            """

            # ── 1. KPI AGGREGATES (session-based) ────────────────────────────
            # total_warnings & false_warnings count unique sessions (0→1).
            # total_detections sums the peak number of children observed in
            # each distinct detection session (cumulative, time-filtered).
            kpi_sql = f"""
                {cte_base}
                SELECT
                    COUNT(*)                    AS total_events,
                    ROUND(AVG(latency_ms), 1)   AS avg_latency,
                    SUM(warn_start)             AS total_warnings,
                    SUM(CASE WHEN detect_start = 1 THEN session_max_children ELSE 0 END) AS total_detections,
                    SUM(false_warn_start)       AS false_warnings
                FROM enriched
                {where_sql}
            """
            cursor.execute(kpi_sql, params)
            kpi = cursor.fetchone()

            # ── 2. TIME-SERIES BINS (session-based) ──────────────────────────
            if time_range in ("15m", "1h"):
                ts_sql = f"""
                    {cte_base}
                    SELECT
                        FLOOR(UNIX_TIMESTAMP(timestamp_iso) / {bin_seconds}) * {bin_seconds} AS bin_ts,
                        SUM(warn_start)    AS warnings,
                        SUM(CASE WHEN detect_start = 1 THEN session_max_children ELSE 0 END) AS detections
                    FROM enriched
                    {where_sql}
                    GROUP BY bin_ts
                    ORDER BY bin_ts
                """
                cursor.execute(ts_sql, params)
                ts_rows = cursor.fetchall()

                time_series = []
                for row in ts_rows:
                    bin_ts_val = int(row["bin_ts"])
                    bin_dt_utc = datetime(1970, 1, 1, tzinfo=timezone.utc) + timedelta(seconds=bin_ts_val)
                    bin_dt_manila = bin_dt_utc.astimezone(manila_tz)
                    label = bin_dt_manila.strftime("%H:%M")
                    time_series.append({
                        "label": label,
                        "ts_ms": bin_ts_val * 1000,
                        "warnings": int(row["warnings"] or 0),
                        "detections": int(row["detections"] or 0)
                    })

            elif time_range == "today":
                ts_sql = f"""
                    {cte_base}
                    SELECT
                        HOUR(timestamp_iso) AS hour_utc,
                        SUM(warn_start)    AS warnings,
                        SUM(CASE WHEN detect_start = 1 THEN session_max_children ELSE 0 END) AS detections
                    FROM enriched
                    {where_sql}
                    GROUP BY hour_utc
                    ORDER BY hour_utc
                """
                cursor.execute(ts_sql, params)
                ts_rows = cursor.fetchall()

                time_series = []
                today_date_utc = range_start_utc.date()
                for row in ts_rows:
                    hour_utc = int(row["hour_utc"])
                    hour_manila = (hour_utc + 8) % 24
                    label = f"{hour_manila:02d}:00"
                    bin_dt = datetime(today_date_utc.year, today_date_utc.month,
                                      today_date_utc.day, hour_utc, 0, 0, tzinfo=timezone.utc)
                    time_series.append({
                        "label": label,
                        "ts_ms": int(bin_dt.timestamp()) * 1000,
                        "warnings": int(row["warnings"] or 0),
                        "detections": int(row["detections"] or 0)
                    })

            else:  # "all" — daily bins
                ts_sql = f"""
                    {cte_base}
                    SELECT
                        DATE(timestamp_iso) AS bin_date,
                        SUM(warn_start)    AS warnings,
                        SUM(CASE WHEN detect_start = 1 THEN session_max_children ELSE 0 END) AS detections
                    FROM enriched
                    {where_sql}
                    GROUP BY bin_date
                    ORDER BY bin_date
                """
                cursor.execute(ts_sql, params)
                ts_rows = cursor.fetchall()

                time_series = []
                for row in ts_rows:
                    bin_date = row["bin_date"]
                    if isinstance(bin_date, datetime):
                        label = bin_date.strftime("%b %d")
                        ts_ms = int(bin_date.replace(tzinfo=timezone.utc).timestamp()) * 1000
                    else:
                        label = str(bin_date)
                        try:
                            d = datetime.strptime(str(bin_date), "%Y-%m-%d").replace(tzinfo=timezone.utc)
                            ts_ms = int(d.timestamp()) * 1000
                        except Exception:
                            ts_ms = 0
                    time_series.append({
                        "label": label,
                        "ts_ms": ts_ms,
                        "warnings": int(row["warnings"] or 0),
                        "detections": int(row["detections"] or 0)
                    })

            # ── 3. PEAK HOUR (session-based, Manila time) ────────────────────
            peak_hour = "--"
            peak_sql = f"""
                {cte_base}
                SELECT
                    HOUR(timestamp_iso)  AS hour_utc,
                    SUM(warn_start)      AS warn_count
                FROM enriched
                {where_sql}
                GROUP BY hour_utc
                ORDER BY warn_count DESC
                LIMIT 1
            """
            cursor.execute(peak_sql, params)
            peak_row = cursor.fetchone()
            if peak_row and peak_row["warn_count"] and int(peak_row["warn_count"]) > 0:
                hour_utc = int(peak_row["hour_utc"])
                hour_manila = (hour_utc + 8) % 24
                ampm = "AM" if hour_manila < 12 else "PM"
                h12 = hour_manila % 12 or 12
                peak_hour = f"{h12} {ampm}"

            # ── 4. CONFIDENCE HISTOGRAM (row-level — not session-based) ──────
            # Counts individual detection rows for distribution analysis.
            conf_sql = f"""
                SELECT
                    SUM(confidence < 0.2  AND child_in_roi = 1) AS b0,
                    SUM(confidence >= 0.2 AND confidence < 0.4 AND child_in_roi = 1) AS b1,
                    SUM(confidence >= 0.4 AND confidence < 0.6 AND child_in_roi = 1) AS b2,
                    SUM(confidence >= 0.6 AND confidence < 0.8 AND child_in_roi = 1) AS b3,
                    SUM(confidence >= 0.8 AND child_in_roi = 1) AS b4
                FROM events
                {where_sql}
            """
            cursor.execute(conf_sql, params)
            conf_row = cursor.fetchone()
            confidence_bins = [
                int(conf_row.get("b0") or 0),
                int(conf_row.get("b1") or 0),
                int(conf_row.get("b2") or 0),
                int(conf_row.get("b3") or 0),
                int(conf_row.get("b4") or 0)
            ] if conf_row else [0, 0, 0, 0, 0]

            # ── 5. SCENARIO DISTRIBUTION (dynamic time-based labeling) ─────
            # Instead of reading the raw 'scenario' column, we compute the
            # label from each event's timestamp (converted to Manila UTC+8).
            # This retroactively classifies ALL historical data correctly.
            manila_t = "TIME(DATE_ADD(timestamp_iso, INTERVAL 8 HOUR))"
            scenario_case = f"""
                CASE
                    WHEN {manila_t} >= '06:00:00' AND {manila_t} < '08:30:00'
                        THEN 'Morning School Entry'
                    WHEN {manila_t} >= '11:00:00' AND {manila_t} < '13:30:00'
                        THEN 'Mid-Day Shift'
                    WHEN {manila_t} >= '15:30:00' AND {manila_t} < '17:00:00'
                        THEN 'Afternoon Dismissal'
                    ELSE 'Standard Daylight Ops'
                END
            """
            scen_sql = f"""
                SELECT {scenario_case} AS time_scenario, COUNT(*) AS cnt
                FROM events
                {where_sql}
                GROUP BY time_scenario
                ORDER BY cnt DESC
                LIMIT 10
            """
            cursor.execute(scen_sql, params)
            scen_rows = cursor.fetchall()
            scenario_distribution = [
                {"scenario": r["time_scenario"] or "Unknown", "count": int(r["cnt"])}
                for r in scen_rows
            ]
            top_scenario = scenario_distribution[0]["scenario"] if scenario_distribution else None

            return {
                "total_events":           int(kpi["total_events"] or 0),
                "total_warnings":         int(kpi["total_warnings"] or 0),
                "total_detections":       int(kpi["total_detections"] or 0),
                "false_warnings":         int(kpi["false_warnings"] or 0),
                "avg_latency":            float(kpi["avg_latency"] or 0),
                "peak_hour":              peak_hour,
                "time_series":            time_series,
                "confidence_bins":        confidence_bins,
                "scenario_distribution":  scenario_distribution,
                "top_scenario":           top_scenario,
                "range_start": range_start_utc.strftime("%Y-%m-%dT%H:%M:%SZ") if range_start_utc else None,
                "range_end":   range_end_utc.strftime("%Y-%m-%dT%H:%M:%SZ"),
                "bin_unit":    bin_unit
            }

    except Exception as e:
        print(f"DB ANALYTICS ERROR: {e}")
        raise e
    finally:
        if conn:
            conn.close()
