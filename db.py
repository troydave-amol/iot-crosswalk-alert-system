import os
import pymysql
import pymysql.cursors
from datetime import datetime
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
                roi_status VARCHAR(8) NOT NULL,
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
    """
    conn = None
    try:
        # Validate required fields (fail early if schema is wrong, but don't crash app)
        required_keys = [
            "timestamp_iso", "source", "child_in_roi", "roi_status", 
            "confidence", "latency_ms", "warning_logic_on", "switch_enabled", 
            "warning_device_on", "battery_percent", "solar_status"
        ]
        for key in required_keys:
            if key not in payload:
                print(f"DB INSERT FAILED: Missing key {key}")
                return

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
                warning_logic_on, switch_enabled, warning_device_on, battery_percent, solar_status,
                scenario, camera_status, edge_status, led_driver_status
            ) VALUES (
                %s, %s, %s, %s, %s, %s,
                %s, %s, %s, %s, %s,
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
                payload["battery_percent"],
                payload["solar_status"],
                payload.get("scenario"),
                payload.get("camera_status"),
                payload.get("edge_status"),
                payload.get("led_driver_status")
            )
            
            cursor.execute(sql, values)
            print(f"DB INSERT OK: {ts_val} warning_device_on={int(payload['warning_device_on'])} child_in_roi={int(payload['child_in_roi'])}")

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

        # Build WHERE clause
        conditions = []
        params = []

        # 1. Time Range — use UTC_TIMESTAMP() to match UTC-stored timestamps
        if time_range == "15m":
            conditions.append("timestamp_iso >= DATE_SUB(UTC_TIMESTAMP(), INTERVAL 15 MINUTE)")
        elif time_range == "1h":
            conditions.append("timestamp_iso >= DATE_SUB(UTC_TIMESTAMP(), INTERVAL 1 HOUR)")
        elif time_range == "today":
            conditions.append("timestamp_iso >= UTC_DATE()") # User required UTC_DATE()
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

        # 4. Scenario (Exact Match)
        if scenario:
            conditions.append("scenario = %s")
            params.append(scenario)

        # 5. Search (Flexible)
        if search:
            # Search across source, scenario, roi_status
            search_clause = "(source LIKE %s OR scenario LIKE %s OR roi_status LIKE %s)"
            conditions.append(search_clause)
            search_pattern = f"%{search}%"
            params.extend([search_pattern, search_pattern, search_pattern])

        where_sql = ""
        if conditions:
            where_sql = "WHERE " + " AND ".join(conditions)

        with conn.cursor() as cursor:
            # A. Get Total Count (for pagination)
            count_sql = f"SELECT COUNT(*) as total FROM events {where_sql}"
            cursor.execute(count_sql, params)
            total_rows = cursor.fetchone()["total"]

            # B. Fetch Data
            # Explicit columns only
            fields = [
                "id", "timestamp_iso", "source", "child_in_roi", "roi_status", 
                "confidence", "latency_ms", "warning_logic_on", "switch_enabled", 
                "warning_device_on", "battery_percent", "solar_status", 
                "scenario", "camera_status", "edge_status", "led_driver_status"
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
