# Directive: API Analytics Aggregates

## Goal

Keep `/api/analytics` aligned with the SQL truth in `db.py` and with the KPI cards and charts rendered by the dashboard.

## Supported Request

```text
GET /api/analytics?range=<15m|1h|today|all>
```

Invalid `range` values should return HTTP `400` with:

```json
{
  "ok": false,
  "error": "invalid_range"
}
```

DB failures should return HTTP `503` with:

```json
{
  "ok": false,
  "error": "db_unavailable"
}
```

## Current Response Contract

The backend currently returns:

```json
{
  "ok": true,
  "range": "today",
  "timezone": "Asia/Manila",
  "bin_unit": "1h",
  "range_start": "2026-04-04T16:00:00Z",
  "range_end": "2026-04-05T08:30:00Z",
  "total_events": 0,
  "total_warnings": 0,
  "total_detections": 0,
  "false_warnings": 0,
  "avg_latency": 0.0,
  "peak_hour": "--",
  "peak_hour_basis": "warnings",
  "top_scenario": null,
  "confidence_bins": [0, 0, 0, 0, 0],
  "scenario_distribution": [],
  "time_series": [
    {
      "label": "08:00",
      "ts_ms": 1712304000000,
      "warnings": 0,
      "detections": 0
    }
  ]
}
```

## Range And Binning Rules

Current implementation in `db.py` uses:

| Range | Window basis | Bin size |
|---|---|---|
| `15m` | rolling UTC 15 minutes | `1m` |
| `1h` | rolling UTC 1 hour | `5m` |
| `today` | Asia/Manila midnight converted to UTC | `1h` |
| `all` | full retained history | `1d` |

Invariant expectations:

- `total_events(15m) <= total_events(1h) <= total_events(today) <= total_events(all)`
- `total_warnings(15m) <= total_warnings(1h) <= total_warnings(today) <= total_warnings(all)`
- `total_detections(15m) <= total_detections(1h) <= total_detections(today) <= total_detections(all)`

## SQL Aggregates Used Today

The current analytics implementation computes:

- `total_events`
- `total_warnings`
- `total_detections`
- `false_warnings`
- `avg_latency`
- `peak_hour`
- `confidence_bins`
- `scenario_distribution`
- `top_scenario`
- `time_series`

Important naming note:

- the live API field is `avg_latency`
- older docs and helper scripts still reference `avg_latency_ms`

## Validation Checklist

1. Start the Flask app and confirm `/api/health` responds.
2. For each supported range, compare API totals against direct SQL counts from the `events` table.
3. Verify `range_start` and `range_end` are frozen for a single request and are emitted as UTC ISO strings.
4. Verify chart series are built from `time_series`, not from paginated `/api/events` rows.
5. Confirm the subset invariants still hold after inserting new rows.

## Script Reality Check

Useful today:

- `scripts/smoke_test_api.py`
  - basic endpoint and range coverage once the app is running

Needs refresh before trust:

- `scripts/verify_db.py`
  - still uses `created_at`, but the current table column is `timestamp_iso`
  - still expects `avg_latency_ms`, but the current API returns `avg_latency`

## Edge Cases

- empty datasets should return zeros and empty lists, not crashes
- `peak_hour` should remain `--` when there are no warnings
- `confidence_bins` should stay five elements long
- all calculations must continue to work even when the `events` table grows beyond the current page size used by the logs page
