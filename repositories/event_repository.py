"""

event_repository.py — Detection event storage, retrieval, streaming, and analytics.



Contains all database operations for the ``events`` table:

- insert_event: write detection payloads

- fetch_events: paginated filtered retrieval

- stream_events: server-side cursor streaming for CSV/JSON export

- fetch_analytics_aggregates: 3-step CTE session-based analytics pipeline



All methods use connection-per-call (stateless).  No shared state.

"""



import os

from datetime import datetime, timezone, timedelta



import pymysql

import pymysql.cursors

from dotenv import load_dotenv



load_dotenv()





# ────────────────────────────────────────────────────────────────────────────

# Export field ordering (canonical for CSV/JSON audit exports)

# ────────────────────────────────────────────────────────────────────────────

RAW_EXPORT_FIELDS = [

    "id",

    "timestamp_iso",

    "capture_ts",

    "warning_ts",

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





# ────────────────────────────────────────────────────────────────────────────

# Private helpers

# ────────────────────────────────────────────────────────────────────────────



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

    year=None,

    months=None,

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



    # 1. Year / Month Historical Filter (takes precedence over presets/custom range)

    if year:

        yr_num = int(year)

        conditions.append("YEAR(DATE_ADD(timestamp_iso, INTERVAL 8 HOUR)) = %s")

        params.append(yr_num)



        month_list = []

        if months and months != "all":

            if isinstance(months, str):

                for part in months.split(","):

                    part = part.strip()

                    if part.isdigit() and 1 <= int(part) <= 12:

                        month_list.append(int(part))

            elif isinstance(months, (list, tuple, set)):

                for m in months:

                    if isinstance(m, int) and 1 <= m <= 12:

                        month_list.append(m)

                    elif str(m).isdigit() and 1 <= int(str(m)) <= 12:

                        month_list.append(int(str(m)))



        month_list = sorted(list(set(month_list)))

        if month_list:

            placeholders = ", ".join(["%s"] * len(month_list))

            conditions.append(f"MONTH(DATE_ADD(timestamp_iso, INTERVAL 8 HOUR)) IN ({placeholders})")

            params.extend(month_list)



    else:

        # Custom Date Range vs Preset Time Range

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



    # 5. Search (Flexible — includes computed scenario label + Manila timestamp in both ISO and MM/DD/YYYY formats)

    if search:

        manila_ts = "DATE_FORMAT(DATE_ADD(timestamp_iso, INTERVAL 8 HOUR), '%%Y-%%m-%%d %%h:%%i:%%s %%p')"

        manila_ts_display = "DATE_FORMAT(DATE_ADD(timestamp_iso, INTERVAL 8 HOUR), '%%m/%%d/%%Y, %%h:%%i:%%s %%p')"

        search_clause = (

            f"(source LIKE %s OR {scenario_case} LIKE %s"

            f" OR roi_status LIKE %s OR {manila_ts} LIKE %s OR {manila_ts_display} LIKE %s)"

        )

        conditions.append(search_clause)

        search_pattern = f"%{search}%"

        params.extend([search_pattern, search_pattern, search_pattern, search_pattern, search_pattern])



    where_sql = ""

    if conditions:

        where_sql = "WHERE " + " AND ".join(conditions)



    return where_sql, params, scenario_case





class EventRepository:

    """Data-access object for the ``events`` table."""



    def insert(self, payload):

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

                    timestamp_iso, capture_ts, warning_ts,

                    source, child_in_roi, roi_status, confidence, latency_ms,

                    warning_logic_on, switch_enabled, warning_device_on, child_count,

                    battery_percent, solar_status,

                    scenario, camera_status, edge_status, led_driver_status

                ) VALUES (

                    %s, %s, %s,

                    %s, %s, %s, %s, %s,

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

                    ts_val = ts_str  # Fallback to original string



                values = (

                    ts_val,

                    payload.get("capture_ts"),

                    payload.get("warning_ts"),

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



    def fetch(

        self,

        limit=50,

        offset=0,

        time_range="all",

        start_date=None,

        end_date=None,

        year=None,

        months=None,

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

                year=year,

                months=months,

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



    def stream(

        self,

        time_range="all",

        start_date=None,

        end_date=None,

        year=None,

        months=None,

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

                year=year,

                months=months,

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



    def _resolve_granularity(self, span_seconds):

        """

        Given the total span in seconds, return (bin_seconds, bin_unit) for

        multi-tier dynamic aggregation:

          ≤ 30 min   →  1m   (60s)

          ≤ 3 h      →  5m   (300s)

          ≤ 3 d      →  1h   (3600s)

          ≤ 30 d     →  1d   (86400s)

          ≤ 90 d     →  1w   (604800s)

          > 90 d     →  1mo  (special — handled via DATE_FORMAT monthly grouping)

        """

        if span_seconds <= 1800:          # ≤ 30 min

            return 60, "1m"

        elif span_seconds <= 10800:       # ≤ 3 h

            return 300, "5m"

        elif span_seconds <= 259200:      # ≤ 3 d

            return 3600, "1h"

        elif span_seconds <= 2592000:     # ≤ 30 d

            return 86400, "1d"

        elif span_seconds <= 7776000:     # ≤ 90 d

            return 604800, "1w"

        else:                             # > 90 d

            return 0, "1mo"               # 0 signals monthly grouping



    def fetch_analytics(self, time_range="all", start_date=None, end_date=None, year=None, months=None):

        """

        Returns server-side computed analytics aggregates for a given time range.

        ALL matching rows are processed in SQL — never bounded by a page limit.

        Timezone: 'today' uses Asia/Manila (UTC+8) midnight; rolling ranges use UTC.



        Custom date range / Year & Months historical filter:

            When ``year`` (and optional ``months``) are provided, filters precisely by

            historical year/months in Asia/Manila local time.

            When ``start_date`` and/or ``end_date`` are provided (ISO strings),

            they override the preset ``time_range``. Granularity is auto-resolved

            from the actual span via ``_resolve_granularity()``.



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

            range_end_utc = now_utc

            range_start_utc = None



            # Preset ranges take strict precedence over any stale/lingering historical parameters
            if time_range in ("15m", "1h", "today", "all"):
                year = None
                months = None
                start_date = None
                end_date = None

            # ── Year / Month Historical Filter (when range is custom or year explicitly specified) ───
            if year:
                time_range = "custom"
                yr_num = int(year)

                conditions.append("YEAR(DATE_ADD(timestamp_iso, INTERVAL 8 HOUR)) = %s")

                params.append(yr_num)



                month_list = []

                if months and months != "all":

                    if isinstance(months, str):

                        for part in months.split(","):

                            part = part.strip()

                            if part.isdigit() and 1 <= int(part) <= 12:

                                month_list.append(int(part))

                    elif isinstance(months, (list, tuple, set)):

                        for m in months:

                            if isinstance(m, int) and 1 <= m <= 12:

                                month_list.append(m)

                            elif str(m).isdigit() and 1 <= int(str(m)) <= 12:

                                month_list.append(int(str(m)))



                month_list = sorted(list(set(month_list)))



                if month_list:

                    placeholders = ", ".join(["%s"] * len(month_list))

                    conditions.append(f"MONTH(DATE_ADD(timestamp_iso, INTERVAL 8 HOUR)) IN ({placeholders})")

                    params.extend(month_list)



                    if len(month_list) == 1:

                        bin_seconds = 86400

                        bin_unit = "1d"

                    else:

                        bin_seconds = 0

                        bin_unit = "1mo"



                    min_m = min(month_list)

                    max_m = max(month_list)

                    m_start = datetime(yr_num, min_m, 1, tzinfo=manila_tz)

                    if max_m == 12:

                        m_end = datetime(yr_num + 1, 1, 1, tzinfo=manila_tz) - timedelta(seconds=1)

                    else:

                        m_end = datetime(yr_num, max_m + 1, 1, tzinfo=manila_tz) - timedelta(seconds=1)

                    range_start_utc = m_start.astimezone(timezone.utc)

                    range_end_utc = m_end.astimezone(timezone.utc)

                else:

                    bin_seconds = 0

                    bin_unit = "1mo"

                    y_start = datetime(yr_num, 1, 1, tzinfo=manila_tz)

                    y_end = datetime(yr_num + 1, 1, 1, tzinfo=manila_tz) - timedelta(seconds=1)

                    range_start_utc = y_start.astimezone(timezone.utc)

                    range_end_utc = y_end.astimezone(timezone.utc)



            # ── Custom date range (start_date / end_date) ────────────────────

            elif start_date or end_date:

                time_range = "custom"

                if start_date:

                    try:

                        # Accept "YYYY-MM-DD" or "YYYY-MM-DDTHH:MM" from the HTML date/datetime-local input

                        sd = datetime.fromisoformat(start_date.replace("Z", "+00:00"))

                        if sd.tzinfo is None:

                            # Treat naive input as Manila local time, convert to UTC

                            sd = sd.replace(tzinfo=manila_tz).astimezone(timezone.utc)

                        range_start_utc = sd

                    except ValueError:

                        range_start_utc = None

                else:

                    range_start_utc = None



                if end_date:

                    try:

                        ed = datetime.fromisoformat(end_date.replace("Z", "+00:00"))

                        if ed.tzinfo is None:

                            ed = ed.replace(tzinfo=manila_tz).astimezone(timezone.utc)

                        range_end_utc = ed

                    except ValueError:

                        range_end_utc = now_utc

                else:

                    range_end_utc = now_utc



                if range_start_utc:

                    conditions.append("timestamp_iso >= %s")

                    params.append(range_start_utc.strftime("%Y-%m-%d %H:%M:%S"))

                    span_seconds = (range_end_utc - range_start_utc).total_seconds()

                else:

                    span_seconds = (range_end_utc - datetime(2020, 1, 1, tzinfo=timezone.utc)).total_seconds()



                bin_seconds, bin_unit = self._resolve_granularity(max(span_seconds, 0))



            elif time_range == "15m":

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



            else:  # "all" — dynamic granularity based on actual data span

                range_start_utc = None

                # For "all", we resolve granularity dynamically after we know the data span.

                # Peek at MIN(timestamp_iso) to compute the actual span.

                with conn.cursor() as _peek_cursor:

                    _peek_cursor.execute("SELECT MIN(timestamp_iso) AS min_ts FROM events")

                    peek_row = _peek_cursor.fetchone()

                    if peek_row and peek_row["min_ts"]:

                        min_ts = peek_row["min_ts"]

                        if isinstance(min_ts, str):

                            min_ts = datetime.strptime(min_ts, "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)

                        elif min_ts.tzinfo is None:

                            min_ts = min_ts.replace(tzinfo=timezone.utc)

                        span_seconds = (now_utc - min_ts).total_seconds()

                    else:

                        span_seconds = 0

                bin_seconds, bin_unit = self._resolve_granularity(max(span_seconds, 0))



            # Freeze range_end once so every query in this request sees the same closed window.

            # Without this, each of the 5 queries could read different totals as new rows are inserted.

            if time_range != "custom":

                range_end_utc = now_utc

            range_end_str = range_end_utc.strftime("%Y-%m-%d %H:%M:%S")

            if not year:

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

                        ROUND(AVG(CASE WHEN latency_ms > 0 AND latency_ms <= 2000 THEN latency_ms END), 1) AS avg_latency,

                        MAX(CASE WHEN latency_ms > 0 AND latency_ms <= 2000 THEN latency_ms END) AS peak_latency,

                        SUM(warn_start)             AS total_warnings,

                        SUM(CASE WHEN detect_start = 1 THEN session_max_children ELSE 0 END) AS total_detections,

                        SUM(false_warn_start)       AS false_warnings

                    FROM enriched

                    {where_sql}

                """

                cursor.execute(kpi_sql, params)

                kpi = cursor.fetchone()



                # ── 2. TIME-SERIES BINS (session-based, dynamic granularity) ──────

                manila_tz_local = manila_tz  # capture for closures



                if bin_unit == "1mo":

                    # Monthly aggregation — group by YYYY-MM in Manila time

                    ts_sql = f"""

                        {cte_base}

                        SELECT

                            DATE_FORMAT(DATE_ADD(timestamp_iso, INTERVAL 8 HOUR), '%%Y-%%m') AS bin_month,

                            MIN(timestamp_iso) AS first_ts,

                            SUM(warn_start)    AS warnings,

                            SUM(CASE WHEN detect_start = 1 THEN session_max_children ELSE 0 END) AS detections

                        FROM enriched

                        {where_sql}

                        GROUP BY bin_month

                        ORDER BY bin_month

                    """

                    cursor.execute(ts_sql, params)

                    ts_rows = cursor.fetchall()



                    time_series = []

                    for row in ts_rows:

                        bm = row["bin_month"]  # e.g. "2026-08"

                        try:

                            d = datetime.strptime(str(bm) + "-01", "%Y-%m-%d").replace(tzinfo=timezone.utc)

                            d_manila = d.astimezone(manila_tz_local)

                            label = d_manila.strftime("%b %Y")

                            ts_ms = int(d.timestamp()) * 1000

                        except Exception:

                            label = str(bm)

                            ts_ms = 0

                        time_series.append({

                            "label": label,

                            "ts_ms": ts_ms,

                            "warnings": int(row["warnings"] or 0),

                            "detections": int(row["detections"] or 0)

                        })



                elif bin_unit == "1w":

                    # Weekly aggregation — group by ISO year-week

                    ts_sql = f"""

                        {cte_base}

                        SELECT

                            DATE(DATE_SUB(timestamp_iso, INTERVAL WEEKDAY(timestamp_iso) DAY)) AS week_start,

                            SUM(warn_start)    AS warnings,

                            SUM(CASE WHEN detect_start = 1 THEN session_max_children ELSE 0 END) AS detections

                        FROM enriched

                        {where_sql}

                        GROUP BY week_start

                        ORDER BY week_start

                    """

                    cursor.execute(ts_sql, params)

                    ts_rows = cursor.fetchall()



                    time_series = []

                    for row in ts_rows:

                        ws = row["week_start"]

                        if isinstance(ws, datetime):

                            ws_manila = ws.replace(tzinfo=timezone.utc).astimezone(manila_tz_local)

                            label = "W " + ws_manila.strftime("%b %d")

                            ts_ms = int(ws.replace(tzinfo=timezone.utc).timestamp()) * 1000

                        else:

                            try:

                                d = datetime.strptime(str(ws), "%Y-%m-%d").replace(tzinfo=timezone.utc)

                                d_manila = d.astimezone(manila_tz_local)

                                label = "W " + d_manila.strftime("%b %d")

                                ts_ms = int(d.timestamp()) * 1000

                            except Exception:

                                label = str(ws)

                                ts_ms = 0

                        time_series.append({

                            "label": label,

                            "ts_ms": ts_ms,

                            "warnings": int(row["warnings"] or 0),

                            "detections": int(row["detections"] or 0)

                        })



                elif bin_unit == "1d":

                    # Daily aggregation — DATE() grouping in Manila time

                    ts_sql = f"""

                        {cte_base}

                        SELECT

                            DATE(DATE_ADD(timestamp_iso, INTERVAL 8 HOUR)) AS bin_date,

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



                else:

                    # Sub-day aggregation (1m, 5m, 1h) — FLOOR(UNIX_TIMESTAMP / bin_seconds) grouping

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

                        bin_dt_manila = bin_dt_utc.astimezone(manila_tz_local)

                        # If bin spans multiple days, include the date in the label

                        if bin_unit == "1h":

                            label = bin_dt_manila.strftime("%b %d %H:%M") if time_range in ("custom", "all") else bin_dt_manila.strftime("%H:%M")

                        else:

                            label = bin_dt_manila.strftime("%H:%M")

                        time_series.append({

                            "label": label,

                            "ts_ms": bin_ts_val * 1000,

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



                # ── 3b. BUSIEST MONTH (for Selection Summary) ────────────────────

                busiest_month = None

                if year:

                    month_names_map = [

                        "Jan", "Feb", "Mar", "Apr", "May", "Jun",

                        "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"

                    ]

                    busiest_sql = f"""

                        {cte_base}

                        SELECT

                            MONTH(DATE_ADD(timestamp_iso, INTERVAL 8 HOUR)) AS mo_num,

                            SUM(warn_start) AS warn_cnt

                        FROM enriched

                        {where_sql}

                        GROUP BY mo_num

                        ORDER BY warn_cnt DESC, mo_num ASC

                        LIMIT 1

                    """

                    cursor.execute(busiest_sql, params)

                    b_row = cursor.fetchone()

                    if b_row and b_row.get("mo_num"):

                        mo_idx = int(b_row["mo_num"])

                        busiest_month = f"{month_names_map[mo_idx - 1]} {yr_num}"



                # ── 3c. DAILY WARNINGS (for Calendar Heatmap) ────────────────────
                # Session-based warning activations aggregated by day (Asia/Manila time)
                daily_warn_sql = f"""
                    {cte_base}
                    SELECT
                        DATE_FORMAT(DATE_ADD(timestamp_iso, INTERVAL 8 HOUR), '%%Y-%%m-%%d') AS day_date,
                        SUM(warn_start) AS warnings
                    FROM enriched
                    {where_sql}
                    GROUP BY day_date
                    ORDER BY day_date
                """
                cursor.execute(daily_warn_sql, params)
                daily_rows = cursor.fetchall()
                daily_warnings = {
                    str(r["day_date"]): int(r["warnings"] or 0)
                    for r in daily_rows if r.get("day_date")
                }



                # ── 4. CONFIDENCE HISTOGRAM & METRICS (10 fine-grained bins, atomic calculation) ──
                # Counts individual detection rows for distribution analysis across 10 decile bins.
                warning_threshold = float(os.getenv("LIVE_CHILD_CONF", "0.65"))
                conf_sql = f"""
                    SELECT
                        SUM(confidence < 0.1 AND child_in_roi = 1) AS b0,
                        SUM(confidence >= 0.1 AND confidence < 0.2 AND child_in_roi = 1) AS b1,
                        SUM(confidence >= 0.2 AND confidence < 0.3 AND child_in_roi = 1) AS b2,
                        SUM(confidence >= 0.3 AND confidence < 0.4 AND child_in_roi = 1) AS b3,
                        SUM(confidence >= 0.4 AND confidence < 0.5 AND child_in_roi = 1) AS b4,
                        SUM(confidence >= 0.5 AND confidence < 0.6 AND child_in_roi = 1) AS b5,
                        SUM(confidence >= 0.6 AND confidence < 0.7 AND child_in_roi = 1) AS b6,
                        SUM(confidence >= 0.7 AND confidence < 0.8 AND child_in_roi = 1) AS b7,
                        SUM(confidence >= 0.8 AND confidence < 0.9 AND child_in_roi = 1) AS b8,
                        SUM(confidence >= 0.9 AND child_in_roi = 1) AS b9,
                        COUNT(CASE WHEN child_in_roi = 1 THEN 1 END) AS total_roi_detections,
                        SUM(CASE WHEN child_in_roi = 1 AND confidence >= {warning_threshold} THEN 1 ELSE 0 END) AS above_threshold,
                        AVG(CASE WHEN child_in_roi = 1 THEN confidence END) AS mean_confidence
                    FROM events
                    {where_sql}
                """
                cursor.execute(conf_sql, params)
                conf_row = cursor.fetchone()
                above_thresh = int(conf_row.get("above_threshold") or 0) if conf_row else 0
                total_roi = int(conf_row.get("total_roi_detections") or 0) if conf_row else 0
                cleared_pct = round((above_thresh / total_roi * 100), 1) if total_roi > 0 else 0.0
                mean_conf = round(float(conf_row.get("mean_confidence") or 0.0), 3) if conf_row and conf_row.get("mean_confidence") is not None else 0.0
                confidence_bins = [
                    int(conf_row.get(f"b{i}") or 0) for i in range(10)
                ] if conf_row else [0] * 10



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

                # Build a lookup from query results

                scen_counts = {

                    r["time_scenario"]: int(r["cnt"])

                    for r in scen_rows if r.get("time_scenario")

                }



                # Canonical 4 operational windows in fixed schedule order.

                # Guarantees the frontend always receives all 4 categories

                # even when a time window has zero events in the active range.

                CANONICAL_SCENARIOS = [

                    "Morning School Entry",

                    "Mid-Day Shift",

                    "Afternoon Dismissal",

                    "Standard Daylight Ops"

                ]

                scenario_distribution = [

                    {"scenario": s, "count": scen_counts.get(s, 0)}

                    for s in CANONICAL_SCENARIOS

                ]

                # Preserve any unexpected scenario labels that fall outside

                # the canonical set (defensive — should not happen in practice)

                for k, v in scen_counts.items():

                    if k not in CANONICAL_SCENARIOS:

                        scenario_distribution.append({"scenario": k, "count": v})



                # top_scenario = highest-count window (skip zero-only)

                active_scens = sorted(

                    [s for s in scenario_distribution if s["count"] > 0],

                    key=lambda x: x["count"], reverse=True

                )

                top_scenario = (

                    active_scens[0]["scenario"] if active_scens

                    else None

                )



                total_w = int(kpi["total_warnings"] or 0)

                false_w = int(kpi["false_warnings"] or 0)

                fwr = round((false_w / total_w * 100), 1) if total_w > 0 else 0.0



                return {

                    "total_events":           int(kpi["total_events"] or 0),

                    "total_warnings":         total_w,

                    "total_detections":       int(kpi["total_detections"] or 0),

                    "false_warnings":         false_w,

                    "false_warning_rate":     fwr,

                    "avg_latency":            float(kpi["avg_latency"] or 0),

                    "peak_latency":           int(kpi["peak_latency"] or 0),

                    "peak_hour":              peak_hour,

                    "time_series":            time_series,
                    "daily_warnings":         daily_warnings,

                    "confidence_bins":            confidence_bins,
                    "confidence_cleared_pct":     cleared_pct,
                    "confidence_above_threshold": above_thresh,
                    "confidence_total_detections": total_roi,
                    "confidence_mean":            mean_conf,
                    "warning_threshold":          warning_threshold,

                    "scenario_distribution":  scenario_distribution,

                    "top_scenario":           top_scenario,

                    "busiest_month":          busiest_month,

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



    def fetch_available_dates(self):

        """

        Returns distinct years and months that have recorded events.

        Useful for dynamic date picker chip/filter generation.

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

            with conn.cursor() as cursor:

                # Group by Manila local time (UTC+8) year and month

                cursor.execute("""

                    SELECT 

                        YEAR(DATE_ADD(timestamp_iso, INTERVAL 8 HOUR)) AS yr,

                        MONTH(DATE_ADD(timestamp_iso, INTERVAL 8 HOUR)) AS mo,

                        COUNT(*) AS cnt

                    FROM events

                    GROUP BY yr, mo

                    ORDER BY yr ASC, mo ASC

                """)

                rows = cursor.fetchall()



            years_set = set()

            months_by_year = {}

            counts = {}



            for r in rows:

                yr = int(r["yr"])

                mo = int(r["mo"])

                cnt = int(r["cnt"])

                years_set.add(yr)

                if yr not in months_by_year:

                    months_by_year[yr] = []

                months_by_year[yr].append(mo)

                counts[f"{yr}-{mo}"] = cnt



            return {

                "years": sorted(list(years_set)),

                "months_by_year": months_by_year,

                "counts": counts

            }

        except Exception as e:

            print(f"DB FETCH AVAILABLE DATES ERROR: {e}")

            raise e

        finally:

            if conn:

                conn.close()





