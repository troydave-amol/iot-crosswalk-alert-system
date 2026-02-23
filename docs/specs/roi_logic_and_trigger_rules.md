# Directive: ROI Logic and Trigger Rules

## Goal
Define the deterministic rules for when the visual warning device is activated or deactivated based on child pedestrian detection within the Crosswalk ROI.

## Scope
- **In scope**: ROI polygon definition, entry/exit detection, `warning_device_on` state, event logging
- **Out of scope**: SMS, audio/sirens/buzzers, face recognition, speed detection, biological age estimation

## Non-Negotiable Rules

| Condition | Warning State |
|-----------|--------------|
| ≥1 child-classified pedestrian inside Crosswalk ROI | `warning_device_on = TRUE` |
| 0 child-classified pedestrians inside Crosswalk ROI | `warning_device_on = FALSE` |

A "child-classified pedestrian" is defined as: **visually classified as a child based on body size, proportions, and school-age appearance** — NOT by biological age.

## ROI Definition
- The Crosswalk ROI is a polygon defined in pixel coordinates at inference time.
- A detection is **inside the ROI** if the center-bottom point of the bounding box falls within the polygon.
- ROI coordinates must be configurable (stored in `.env` or config file, not hardcoded).

## Trigger Logic (Pseudocode)
```
children_in_roi = [d for d in detections if d.class == "child" and point_in_polygon(d.bbox_bottom_center, ROI)]
child_in_roi    = len(children_in_roi) > 0
warning_device_on = child_in_roi

emit status_update:
  timestamp_iso     = utcnow().isoformat()
  warning_device_on = warning_device_on
  child_in_roi      = child_in_roi
  confidence        = max(d.confidence for d in children_in_roi) if child_in_roi else 0.0
  latency_ms        = inference_time_ms
```

## Event Logging
- Log to MySQL `events` table **only on state change** (edge-triggered), not every frame.
- State change = `warning_device_on` flipped from previous frame.
- Edge cases: first frame always logs; if DB is down, continue running (no crash).

## Canonical Fields
```
timestamp_iso     — UTC ISO 8601
warning_device_on — boolean (1/0 in MySQL)
child_in_roi      — boolean (1/0 in MySQL)
confidence        — float [0.0, 1.0]
latency_ms        — int (ms)
scenario          — optional string tag
```

## Validation Steps
1. Simulate: place bounding box inside ROI → `warning_device_on` must be `1`.
2. Simulate: move bounding box outside ROI → `warning_device_on` must be `0`.
3. Verify `events` table receives exactly one row per state change.
4. Verify DB-down tolerance: inference loop must not crash if MySQL is unavailable.

## Edge Cases
- Partial bbox overlap with ROI → use center-bottom point as sole criterion.
- Multiple children in ROI → `warning_device_on = 1`, confidence = max of all confidences.
- ROI not configured → system must halt with a clear config error, not silently ignore.
