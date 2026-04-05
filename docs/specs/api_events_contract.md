# API Event And Status Contract

This document reflects the API surface currently implemented in `app.py` and `db.py`.

## Canonical Live Status Payload

`status_update` is emitted over Socket.IO and is also the shape the frontend contract validator expects.

Required fields:

| Field | Type | Notes |
|---|---|---|
| `timestamp_iso` | string | UTC ISO timestamp |
| `child_in_roi` | boolean | stabilized child-in-ROI flag |
| `roi_status` | string | currently `CHILD_IN_ROI` or `CLEAR` from the backend |
| `confidence` | number | stabilized confidence |
| `latency_ms` | number | integer-like processing latency |
| `warning_device_on` | boolean | final warning output state |

Common optional fields:

| Field | Type | Notes |
|---|---|---|
| `child_in_roi_raw` | boolean | raw pre-stabilized state |
| `confidence_raw` | number | raw pre-stabilized confidence |
| `source` | string | usually `yolo` or `idle` |
| `camera_status` | string | present on idle payloads |
| `edge_status` | string | present on idle payloads |

Frontend compatibility note:

- `static/js/dashboard.js` still supports a legacy fallback named `warning_on`.
- backend code should continue using `warning_device_on` as the source of truth.

## GET /api/events

Returns filtered event rows from MySQL.

### Query parameters

| Param | Type | Notes |
|---|---|---|
| `range` | `15m` \| `1h` \| `today` \| `all` | default `all` |
| `limit` | int | default `50`, capped at `500` |
| `offset` | int | default `0` |
| `warning_only` | bool-like string | `true` or `1` enables filter |
| `in_roi_only` | bool-like string | `true` or `1` enables filter |
| `min_conf` | float | default `0.0` |
| `scenario` | string | exact-match filter |
| `search` | string | matches `source`, `scenario`, or `roi_status` |

### Response shape

```json
{
  "ok": true,
  "total": 123,
  "rows": [
    {
      "id": 456,
      "timestamp_iso": "2026-04-05T08:20:00Z",
      "source": "yolo",
      "child_in_roi": 1,
      "roi_status": "CHILD_IN_ROI",
      "confidence": 0.91,
      "latency_ms": 43,
      "warning_logic_on": 1,
      "switch_enabled": 1,
      "warning_device_on": 1,
      "battery_percent": 0.0,
      "solar_status": "N/A",
      "scenario": "Live",
      "camera_status": "OK",
      "edge_status": "OK",
      "led_driver_status": "Ready"
    }
  ]
}
```

### Failure behavior

- on DB/query failure: HTTP `503`
- body:

```json
{
  "ok": false,
  "error": "db_unavailable"
}
```

## GET /api/health

Used as a lightweight server health probe.

```json
{
  "ok": true
}
```

This endpoint should respond even if MySQL is down.

## Event Row Rules

- timestamps are stored in MySQL as UTC `DATETIME`
- `today` uses Asia/Manila midnight converted to UTC for filtering
- rows are ordered by newest `id` first
- event logging is driven by state change plus a 10-second heartbeat in the live session classes

## Contract Notes For Maintainers

- the current logs page uses `limit` and `offset`, not `page` and `per_page`
- `roi_status` in the backend currently uses `CHILD_IN_ROI` and `CLEAR`
- the frontend contract validator still accepts `INSIDE` and `OUTSIDE` for backward compatibility
