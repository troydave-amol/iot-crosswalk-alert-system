# Directive: API Analytics Aggregates

## Goal
Ensure `/api/analytics` returns SQL-accurate aggregates that match dashboard KPI displays for all supported time ranges.

## Scope
- **In scope**: Range filtering, aggregate computation (warnings, detections, latency, peak hour), metadata fields
- **Out of scope**: SMS, audio, face recognition — these must NEVER appear in analytics data

## Inputs Required
- MySQL `events` table accessible via `db.py`
- Time range parameter: `range` ∈ `{15m, 1h, today, all}`

## API Contract

### Request
```
GET /api/analytics?range=<15m|1h|today|all>
```

### Response Fields (canonical)
```json
{
  "range": "15m",
  "range_start": "<ISO 8601 UTC>",
  "range_end":   "<ISO 8601 UTC>",
  "timezone":    "Asia/Manila",
  "bin_unit":    "minute|hour|day",
  "total_events":    <int>,
  "total_warnings":  <int>,
  "total_detections":<int>,
  "avg_latency_ms":  <float>,
  "peak_hour":       "<HH:00>",
  "bins": [
    { "bin_label": "...", "warnings": <int>, "detections": <int> }
  ]
}
```

### Range Rules (must always hold)
- `15m ⊆ 1h ⊆ today ⊆ all`
- Totals must satisfy nested subsets: `total_warnings(15m) ≤ total_warnings(1h) ≤ total_warnings(today) ≤ total_warnings(all)`
- On DB error: return HTTP 503 `{ "error": "db_unavailable" }` — do NOT crash

## Tools / Scripts
- `execution/verify_db.py` — run ground-truth SQL and compare to API response
- `execution/smoke_test_api.py` — automated endpoint health and range check

## Validation Steps
1. Run raw SQL for each range: `SELECT COUNT(*) WHERE warning_device_on=1 AND created_at >= <range_start>`.
2. Call `/api/analytics?range=<X>` for same range.
3. Compare `total_warnings` — must match exactly.
4. Verify `range_start` and `range_end` are correct UTC boundaries.
5. Verify subset rule: `total_warnings(15m) ≤ total_warnings(1h)` etc.

## Edge Cases
- Empty result set → return zeros, not null/error.
- DB down → 503 JSON, not 500 crash.
- `today` boundary must use server's local midnight in `Asia/Manila`, stored as UTC.
- `avg_latency_ms` must be `NULL`-safe (use `COALESCE(AVG(latency_ms), 0)`).
