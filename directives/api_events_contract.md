# API Contract Reference

## Canonical Event Fields

| Field | Type | Notes |
|---|---|---|
| `timestamp_iso` | string (ISO 8601 UTC) | Primary timestamp field |
| `warning_device_on` | bool | Canonical warning state |
| `child_in_roi` | bool | Child inside Crosswalk ROI |
| `confidence` | float (0.0–1.0) | Detection confidence |
| `latency_ms` | int | Processing latency in ms |
| `scenario` | string | Optional label |

**Legacy**: `warning_on` is a fallback for `warning_device_on` only. Never use as primary.

---

## GET /api/events

**Query parameters:**

| Param | Values | Notes |
|---|---|---|
| `range` | `15m`, `1h`, `today`, `all` | Time window filter |
| `page` | int (default 1) | Pagination page |
| `per_page` | int (default 50) | Rows per page |

**Response shape:**
```json
{
  "events": [...],
  "total": 123,
  "page": 1,
  "per_page": 50
}
```

**Failure**: Returns HTTP 503 with `{"error": "DB unavailable"}`. Server must NOT crash.

---

## GET /api/analytics

**Response must include:**
```json
{
  "range_start": "<ISO timestamp>",
  "range_end": "<ISO timestamp>",
  "timezone": "UTC",
  "bin_unit": "minute|hour|day",
  "total_warnings": 0,
  "total_detections": 0,
  "avg_latency_ms": 0.0,
  "bins": [...]
}
```

Aggregates must be SQL-accurate and independent of table size.

---

## GET /api/health

```json
{ "ok": true }
```

Must respond even when database is down.

---

## Range Rules (Invariant)

These must ALWAYS hold:

- `15m` total <= `1h` total <= `today` total <= `all` total
- Applies to: events count, warning count, detection count
- Timestamps in MySQL are stored as UTC DATETIME
- All range filtering must use UTC comparison (parameterized SQL only)
- Frontend must pass `range` param matching the active tab selection

---

## Safe Failure Pattern

```python
try:
    # DB query
except Exception as e:
    return jsonify({"error": "DB unavailable", "detail": str(e)}), 503
```
