import os
import pymysql
import pymysql.cursors
from datetime import datetime, timezone, timedelta
from dotenv import load_dotenv
from werkzeug.security import generate_password_hash, check_password_hash

load_dotenv()

def get_connection():
    """
    Creates a new database connection.
    Intentionally determines database presence to allow creation if missing.
    """
    return pymysql.connect(
        host=os.getenv("DB_HOST", "127.0.0.1"),
        user=os.getenv("DB_USER", "root"),
        password=os.getenv("DB_PASS", ""),
        charset='utf8mb4',
        cursorclass=pymysql.cursors.DictCursor,
        autocommit=True
    )

def _get_db_connection():
    """Return a connection to the target database (not root-level)."""
    target_db = os.getenv("DB_NAME", "crosswalk_db")
    return pymysql.connect(
        host=os.getenv("DB_HOST", "127.0.0.1"),
        user=os.getenv("DB_USER", "root"),
        password=os.getenv("DB_PASS", ""),
        database=target_db,
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
            host=os.getenv("DB_HOST", "127.0.0.1"),
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
            
            # Create events table
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

            # ── RBAC: Create users table ──────────────────────────────
            create_users_sql = """
            CREATE TABLE IF NOT EXISTS users (
                id INT AUTO_INCREMENT PRIMARY KEY,
                username VARCHAR(64) NOT NULL UNIQUE,
                password_hash VARCHAR(255) NOT NULL,
                role ENUM('tmc_officer', 'it_specialist') NOT NULL DEFAULT 'tmc_officer',
                full_name VARCHAR(128) NOT NULL,
                created_at DATETIME NOT NULL,
                last_login DATETIME NULL,
                INDEX idx_username (username),
                INDEX idx_role (role)
            )
            """
            cursor.execute(create_users_sql)
            print(f"  → Table 'users' checked/initialized successfully.")

            # Seed default accounts if the users table is empty
            cursor.execute("SELECT COUNT(*) AS cnt FROM users")
            row = cursor.fetchone()
            if row and row["cnt"] == 0:
                now_iso = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")

                # TMC Officer seed
                tmc_user = os.getenv("TMC_USERNAME", "tmc_officer")
                tmc_pass = os.getenv("TMC_PASSWORD", "SmartCrosswalk2026")
                tmc_hash = generate_password_hash(tmc_pass)

                cursor.execute(
                    "INSERT INTO users (username, password_hash, role, full_name, created_at) "
                    "VALUES (%s, %s, %s, %s, %s)",
                    (tmc_user, tmc_hash, "tmc_officer", "TMC Officer", now_iso)
                )

                # IT Specialist seed
                it_user = os.getenv("IT_SPECIALIST_USERNAME", "it_specialist")
                it_pass = os.getenv("IT_SPECIALIST_PASSWORD", "uswagmalaybalay")
                it_hash = generate_password_hash(it_pass)

                cursor.execute(
                    "INSERT INTO users (username, password_hash, role, full_name, created_at) "
                    "VALUES (%s, %s, %s, %s, %s)",
                    (it_user, it_hash, "it_specialist", "IT Systems Specialist", now_iso)
                )

                print(f"  → Seeded default users: '{tmc_user}' (tmc_officer), '{it_user}' (it_specialist)")
            else:
                print(f"  → Users table already populated ({row['cnt']} users). Skipping seed.")

    except Exception as e:
        print(f"DB INIT INVALID: {e}")
        # We do not raise, so the app can continue running even if DB fails
    finally:
        if conn:
            conn.close()


# ────────────────────────────────────────────────────────────────────────────
# RBAC: User Authentication Helpers
# ────────────────────────────────────────────────────────────────────────────

def authenticate_user(username: str, password: str) -> dict | None:
    """
    Authenticate a user against the users table.
    Returns the user row dict on success, None on failure.
    """
    conn = None
    try:
        conn = _get_db_connection()
        with conn.cursor() as cursor:
            cursor.execute("SELECT * FROM users WHERE username = %s", (username,))
            user = cursor.fetchone()
            if user and check_password_hash(user["password_hash"], password):
                # Update last_login timestamp
                now_iso = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
                cursor.execute(
                    "UPDATE users SET last_login = %s WHERE id = %s",
                    (now_iso, user["id"])
                )
                return user
            return None
    except Exception as e:
        print(f"[AUTH] authenticate_user error: {e}")
        return None
    finally:
        if conn:
            conn.close()


def get_user_by_username(username: str) -> dict | None:
    """Fetch a single user row by username. Returns None if not found."""
    conn = None
    try:
        conn = _get_db_connection()
        with conn.cursor() as cursor:
            cursor.execute("SELECT * FROM users WHERE username = %s", (username,))
            return cursor.fetchone()
    except Exception as e:
        print(f"[AUTH] get_user_by_username error: {e}")
        return None
    finally:
        if conn:
            conn.close()


def update_user_password(username: str, new_password: str) -> bool:
    """
    Update a user's password hash in the database.
    Returns True on success, False on failure.
    """
    conn = None
    try:
        conn = _get_db_connection()
        new_hash = generate_password_hash(new_password)
        with conn.cursor() as cursor:
            cursor.execute(
                "UPDATE users SET password_hash = %s WHERE username = %s",
                (new_hash, username)
            )
            return cursor.rowcount > 0
    except Exception as e:
        print(f"[AUTH] update_user_password error: {e}")
        return False
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
        conn = _get_db_connection()

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


RAW_EXPORT_FIELDS = [
    "id",
    "timestamp_iso",
    "source",
    "child_in_roi",
    "roi_status",
    "confidence",
    "latency_ms",
    "warning_logic_on",
    "switch_enabled",
    "warning_device_on",
    "child_count",
    "battery_percent",
    "solar_status",
    "scenario",
    "camera_status",
    "edge_status",
    "led_driver_status",
]


def _parse_to_utc_sql(dt_input, is_end=False):
    """
    Parses datetime input into UTC MySQL format '%Y-%m-%d %H:%M:%S'.
    Accepts:
    - HTML datetime-local format: '2026-08-23T14:30' or '2026-08-23T14:30:00' (assumes Manila local UTC+8)
    - ISO strings with timezone: '2026-08-23T06:30:00Z' or '2026-08-23T14:30:00+08:00'
    - Date-only strings: '2026-08-23' (start of day 00:00:00 or end of day 23:59:59 Manila time)
    """
    if not dt_input:
        return None
    if isinstance(dt_input, datetime):
        if dt_input.tzinfo is None:
            manila_tz = timezone(timedelta(hours=8))
            dt_input = dt_input.replace(tzinfo=manila_tz)
        utc_dt = dt_input.astimezone(timezone.utc)
        return utc_dt.strftime("%Y-%m-%d %H:%M:%S")

    s = str(dt_input).strip()
    if not s:
        return None

    try:
        # ISO format with Z
        if s.endswith("Z"):
            dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
            return dt.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")

        # ISO format with offset (+08:00, -05:00)
        if "+" in s or ("-" in s and len(s) > 10 and s[10] != "-"):
            try:
                dt = datetime.fromisoformat(s)
                if dt.tzinfo is not None:
                    return dt.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
            except Exception:
                pass

        # Date only: YYYY-MM-DD
        if len(s) == 10 and s.count("-") == 2:
            time_part = "23:59:59" if is_end else "00:00:00"
            s = f"{s} {time_part}"

        # Normalize space vs T
        if "T" in s:
            s = s.replace("T", " ")
        if len(s) == 16:  # YYYY-MM-DD HH:MM
            s += ":59" if is_end else ":00"

        # Local Manila time (UTC+8) -> convert to UTC
        local_dt = datetime.strptime(s[:19], "%Y-%m-%d %H:%M:%S")
        utc_dt = local_dt - timedelta(hours=8)
        return utc_dt.strftime("%Y-%m-%d %H:%M:%S")
    except Exception as e:
        print(f"[DB] _parse_to_utc_sql error parsing '{dt_input}': {e}")
        return None


def _build_events_where(
    time_range="all",
    start_date=None,
    end_date=None,
    warning_only=False,
    in_roi_only=False,
    min_conf=0.0,
    scenario=None,
    search=None
):
    # Dynamic time-based scenario label (same logic as analytics chart)
    manila_t = "TIME(DATE_ADD(timestamp_iso, INTERVAL 8 HOUR))"
    scenario_case = f"""CASE
        WHEN {manila_t} >= '06:00:00' AND {manila_t} < '08:30:00' THEN 'Morning School Entry'
        WHEN {manila_t} >= '11:00:00' AND {manila_t} < '13:30:00' THEN 'Mid-Day Shift'
        WHEN {manila_t} >= '15:30:00' AND {manila_t} < '17:00:00' THEN 'Afternoon Dismissal'
        ELSE 'Standard Daylight Ops'
    END"""

    conditions = []
    params = []

    # 1. Custom Date Range vs Preset Time Range
    parsed_start = _parse_to_utc_sql(start_date, is_end=False)
    parsed_end = _parse_to_utc_sql(end_date, is_end=True)

    if parsed_start:
        conditions.append("timestamp_iso >= %s")
        params.append(parsed_start)
    if parsed_end:
        conditions.append("timestamp_iso <= %s")
        params.append(parsed_end)

    if not parsed_start and not parsed_end:
        if time_range == "15m":
            conditions.append("timestamp_iso >= DATE_SUB(UTC_TIMESTAMP(), INTERVAL 15 MINUTE)")
        elif time_range == "1h":
            conditions.append("timestamp_iso >= DATE_SUB(UTC_TIMESTAMP(), INTERVAL 1 HOUR)")
        elif time_range == "today":
            manila_tz = timezone(timedelta(hours=8))
            manila_now = datetime.now(manila_tz)
            manila_today_start = manila_now.replace(hour=0, minute=0, second=0, microsecond=0)
            today_utc = manila_today_start.astimezone(timezone.utc)
            conditions.append("timestamp_iso >= %s")
            params.append(today_utc.strftime("%Y-%m-%d %H:%M:%S"))

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
    if scenario and scenario != "All":
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

    return where_sql, params, scenario_case


def fetch_events(
    limit=50, 
    offset=0, 
    time_range="all", 
    start_date=None,
    end_date=None,
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
        conn = _get_db_connection()

        where_sql, params, scenario_case = _build_events_where(
            time_range=time_range,
            start_date=start_date,
            end_date=end_date,
            warning_only=warning_only,
            in_roi_only=in_roi_only,
            min_conf=min_conf,
            scenario=scenario,
            search=search
        )

        with conn.cursor() as cursor:
            # A. Get Total Count (for pagination)
            count_sql = f"SELECT COUNT(*) as total FROM events {where_sql}"
            cursor.execute(count_sql, params)
            total_rows = cursor.fetchone()["total"]

            # B. Fetch Data
            select_fields = []
            for f in RAW_EXPORT_FIELDS:
                if f == "scenario":
                    select_fields.append(f"{scenario_case} AS scenario")
                else:
                    select_fields.append(f)
            fields_str = ", ".join(select_fields)

            # Order by newest first for UI display
            query_sql = f"""
                SELECT {fields_str} 
                FROM events 
                {where_sql} 
                ORDER BY id DESC 
                LIMIT %s OFFSET %s
            """
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
                    if " " in new_row["timestamp_iso"] and "T" not in new_row["timestamp_iso"]:
                        new_row["timestamp_iso"] = new_row["timestamp_iso"].replace(" ", "T")
                    if not new_row["timestamp_iso"].endswith("Z"):
                        new_row["timestamp_iso"] += "Z"

                # Decimal -> float
                for k, v in new_row.items():
                    if hasattr(v, 'quantize'):
                        new_row[k] = float(v)

                serialized_rows.append(new_row)

            return {
                "total": total_rows,
                "rows": serialized_rows
            }
    finally:
        if conn:
            conn.close()


def stream_events(
    time_range="all",
    start_date=None,
    end_date=None,
    warning_only=False,
    in_roi_only=False,
    min_conf=0.0,
    scenario=None,
    search=None
):
    """
    Generator that streams event rows matching all filters using a server-side cursor (SSDictCursor).
    Yields normalized row dicts one-by-one without buffering the entire dataset in RAM.
    """
    target_db = os.getenv("DB_NAME", "crosswalk_db")
    conn = pymysql.connect(
        host=os.getenv("DB_HOST", "127.0.0.1"),
        user=os.getenv("DB_USER", "root"),
        password=os.getenv("DB_PASS", ""),
        database=target_db,
        charset='utf8mb4',
        cursorclass=pymysql.cursors.SSDictCursor,
        autocommit=True
    )
    try:
        where_sql, params, scenario_case = _build_events_where(
            time_range=time_range,
            start_date=start_date,
            end_date=end_date,
            warning_only=warning_only,
            in_roi_only=in_roi_only,
            min_conf=min_conf,
            scenario=scenario,
            search=search
        )

        select_fields = []
        for f in RAW_EXPORT_FIELDS:
            if f == "scenario":
                select_fields.append(f"{scenario_case} AS scenario")
            else:
                select_fields.append(f)
        fields_str = ", ".join(select_fields)

        query_sql = f"""
            SELECT {fields_str} 
            FROM events 
            {where_sql} 
            ORDER BY id ASC
        """

        with conn.cursor() as cursor:
            cursor.execute(query_sql, params)
            while True:
                row = cursor.fetchone()
                if row is None:
                    break

                # Format timestamp
                if isinstance(row["timestamp_iso"], datetime):
                    row["timestamp_iso"] = row["timestamp_iso"].strftime("%Y-%m-%dT%H:%M:%SZ")
                elif isinstance(row["timestamp_iso"], str):
                    if " " in row["timestamp_iso"] and "T" not in row["timestamp_iso"]:
                        row["timestamp_iso"] = row["timestamp_iso"].replace(" ", "T")
                    if not row["timestamp_iso"].endswith("Z"):
                        row["timestamp_iso"] += "Z"

                for k, v in row.items():
                    if hasattr(v, 'quantize'):
                        row[k] = float(v)

                yield row
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
            host=os.getenv("DB_HOST", "127.0.0.1"),
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
