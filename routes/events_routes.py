"""
events_routes.py — Health check, events listing, export, and analytics endpoints.

Blueprint: ``events_bp``
Routes:
    GET /api/health          → server health check
    GET /api/events          → paginated, filtered event logs
    GET /api/events/export   → streaming CSV/JSON audit export (IT only)
    GET /api/analytics       → session-based analytics aggregates
"""

import csv
import io
import json
from datetime import datetime, timezone

from flask import Blueprint, request, jsonify, Response

from auth.decorators import login_required, role_required
from db import fetch_events, stream_events, fetch_analytics_aggregates, fetch_available_dates, RAW_EXPORT_FIELDS

events_bp = Blueprint("events", __name__)


@events_bp.route("/api/health")
def api_health():
    """
    Simple health check.
    Returns 200 OK if server is running.
    """
    return jsonify({"ok": True})


@events_bp.route("/api/events")
@login_required
def api_events_route():
    """
    Get historical events from DB.
    Returns 503 if DB is unavailable.
    """
    try:
        # Parse Query Params
        range_arg = request.args.get("range", "all")
        start_date = request.args.get("start_date") or request.args.get("start")
        end_date = request.args.get("end_date") or request.args.get("end")
        year = request.args.get("year")
        months = request.args.get("months")
        limit = int(request.args.get("limit", 50))
        offset = int(request.args.get("offset", 0))

        # Boolean flags
        warning_only = request.args.get("warning_only", "false").lower() in ("true", "1")
        in_roi_only = request.args.get("in_roi_only", "false").lower() in ("true", "1")

        min_conf = float(request.args.get("min_conf", 0.0))
        scenario = request.args.get("scenario", None)
        if scenario == "All":
            scenario = None
        search = request.args.get("search", None)

        # Enforce max limit
        if limit > 500:
            limit = 500

        data = fetch_events(
            limit=limit,
            offset=offset,
            time_range=range_arg,
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

        response = {
            "ok": True,
            "total": data["total"],
            "rows": data["rows"]
        }
        return jsonify(response)

    except Exception as e:
        print(f"API EVENTS ERROR: {e}")
        return jsonify({"ok": False, "error": "db_unavailable"}), 503


@events_bp.route("/api/events/export")
@role_required("it_specialist")
def api_events_export_route():
    """
    Stream full raw dataset export (CSV or JSON) respecting all active filters.
    IT Specialist-only.
    """
    try:
        format_type = request.args.get("format", "csv").lower()
        if format_type not in ("csv", "json"):
            return jsonify({"ok": False, "error": "invalid_format", "message": "Format must be 'csv' or 'json'"}), 400

        range_arg = request.args.get("range", "all")
        start_date = request.args.get("start_date") or request.args.get("start")
        end_date = request.args.get("end_date") or request.args.get("end")
        year = request.args.get("year")
        months = request.args.get("months")
        warning_only = request.args.get("warning_only", "false").lower() in ("true", "1")
        in_roi_only = request.args.get("in_roi_only", "false").lower() in ("true", "1")
        min_conf = float(request.args.get("min_conf", 0.0))
        scenario = request.args.get("scenario", None)
        if scenario == "All":
            scenario = None
        search = request.args.get("search", None)

        # Filename generation with timestamp and filter indicator
        now_tag = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        if year:
            range_tag = f"year_{year}"
        elif start_date or end_date:
            range_tag = "custom"
        else:
            range_tag = range_arg

        filename = f"crosswalk_audit_events_{range_tag}_{now_tag}.{format_type}"

        if format_type == "csv":
            def generate_csv():
                output = io.StringIO()
                writer = csv.writer(output)
                # Write CSV header row
                writer.writerow(RAW_EXPORT_FIELDS)
                yield output.getvalue()
                output.seek(0)
                output.truncate(0)

                # Stream matching rows
                for row in stream_events(
                    time_range=range_arg,
                    start_date=start_date,
                    end_date=end_date,
                    year=year,
                    months=months,
                    warning_only=warning_only,
                    in_roi_only=in_roi_only,
                    min_conf=min_conf,
                    scenario=scenario,
                    search=search
                ):
                    writer.writerow([row.get(f, "") for f in RAW_EXPORT_FIELDS])
                    yield output.getvalue()
                    output.seek(0)
                    output.truncate(0)

            return Response(
                generate_csv(),
                mimetype="text/csv; charset=utf-8",
                headers={
                    "Content-Disposition": f"attachment; filename=\"{filename}\"",
                    "Cache-Control": "no-cache"
                }
            )

        elif format_type == "json":
            def generate_json():
                yield "[\n"
                first = True
                for row in stream_events(
                    time_range=range_arg,
                    start_date=start_date,
                    end_date=end_date,
                    year=year,
                    months=months,
                    warning_only=warning_only,
                    in_roi_only=in_roi_only,
                    min_conf=min_conf,
                    scenario=scenario,
                    search=search
                ):
                    if not first:
                        yield ",\n"
                    yield "  " + json.dumps(row, default=str)
                    first = False
                yield "\n]"

            return Response(
                generate_json(),
                mimetype="application/json; charset=utf-8",
                headers={
                    "Content-Disposition": f"attachment; filename=\"{filename}\"",
                    "Cache-Control": "no-cache"
                }
            )

    except Exception as e:
        print(f"API EXPORT ERROR: {e}")
        return jsonify({"ok": False, "error": "export_failed", "message": str(e)}), 500


@events_bp.route("/api/analytics")
@login_required
def api_analytics_route():
    """
    Returns server-side computed analytics aggregates for a given time range.
    Always computes from ALL matching rows in the DB - never limited by page size.
    Timezone: Asia/Manila (UTC+8) for 'today'; UTC rolling windows for '15m' and '1h'.
    """
    try:
        range_arg = request.args.get("range", "all")
        start_date = request.args.get("start_date") or request.args.get("start")
        end_date = request.args.get("end_date") or request.args.get("end")
        year = request.args.get("year")
        months = request.args.get("months")

        if range_arg in ("15m", "1h", "today", "all"):
            # Preset takes precedence: ignore any stale historical or date params
            start_date = None
            end_date = None
            year = None
            months = None
        elif range_arg == "custom" or start_date or end_date or year:
            range_arg = "custom"
        else:
            range_arg = "all"

        if range_arg not in ("15m", "1h", "today", "all", "custom"):
            return jsonify({"ok": False, "error": "invalid_range"}), 400

        agg = fetch_analytics_aggregates(
            time_range=range_arg,
            start_date=start_date,
            end_date=end_date,
            year=year,
            months=months
        )

        response = {
            "ok": True,
            "range": range_arg,
            "timezone": "Asia/Manila",
            "bin_unit": agg.get("bin_unit", "1d"),
            "range_start": agg.get("range_start"),
            "range_end": agg.get("range_end"),
            "total_events": agg["total_events"],
            "total_warnings": agg["total_warnings"],
            "total_detections": agg["total_detections"],
            "false_warnings": agg["false_warnings"],
            "false_warning_rate": agg.get("false_warning_rate", 0),
            "avg_latency": agg["avg_latency"],
            "peak_latency": agg.get("peak_latency", 0),
            "peak_hour": agg["peak_hour"],
            "peak_hour_basis": "warnings",
            "top_scenario": agg.get("top_scenario"),
            "busiest_month": agg.get("busiest_month"),
            "confidence_bins": agg.get("confidence_bins", [0] * 10),
            "confidence_cleared_pct": agg.get("confidence_cleared_pct", 0.0),
            "confidence_above_threshold": agg.get("confidence_above_threshold", 0),
            "confidence_total_detections": agg.get("confidence_total_detections", 0),
            "confidence_mean": agg.get("confidence_mean", 0.0),
            "warning_threshold": agg.get("warning_threshold", 0.65),
            "scenario_distribution": agg.get("scenario_distribution", []),
            "time_series": agg["time_series"],
            "daily_warnings": agg.get("daily_warnings", {})
        }
        return jsonify(response)

    except Exception as e:
        print(f"API ANALYTICS ERROR: {e}")
        return jsonify({"ok": False, "error": "db_unavailable"}), 503


@events_bp.route("/api/analytics/available_dates")
@login_required
def api_analytics_available_dates_route():
    """
    Returns distinct years and months that have events in the DB.
    Used by the Analytics dashboard to dynamically render Year & Month chip selectors.
    """
    try:
        data = fetch_available_dates()
        return jsonify({
            "ok": True,
            **data
        })
    except Exception as e:
        print(f"API AVAILABLE DATES ERROR: {e}")
        return jsonify({"ok": False, "error": "db_unavailable"}), 503



