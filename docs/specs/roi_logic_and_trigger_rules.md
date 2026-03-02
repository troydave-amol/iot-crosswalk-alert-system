# Directive: ROI Logic and Trigger Rules

## Goal
Define deterministic rules for when the visual warning device is activated or deactivated based on child pedestrian detection within the Crosswalk ROI.

## Scope
- In scope: ROI definition, entry/exit detection, `warning_device_on` state, event logging
- Out of scope: SMS, audio/sirens/buzzers, face recognition, speed detection, biological age estimation

## Non-Negotiable Rules

| Condition | Warning State |
|---|---|
| >=1 child-classified pedestrian inside Crosswalk ROI | `warning_device_on = TRUE` |
| 0 child-classified pedestrians inside Crosswalk ROI | `warning_device_on = FALSE` |

A child-classified pedestrian is defined as: visually classified as a child based on body size, proportions, and school-age appearance, not biological age.

## ROI Definition
- ROI is a polygon/rectangle in pixel coordinates at inference time.
- A detection is inside ROI if the bbox bottom-center point is inside ROI.
- ROI coordinates must be configurable (not hardcoded).

## Canonical Trigger Pipeline
1. Run detector on frame with `agnostic_nms=True` and configured IoU threshold.
2. Build raw trigger candidates using:
   - class `child_like`
   - confidence >= `LIVE_CHILD_CONF`
   - bbox height >= `LIVE_MIN_CHILD_BBOX_RATIO * frame_height`
   - bbox bottom-center inside ROI
3. Apply overlap dominance on trigger candidates only (keep higher-confidence candidate when IoU >= configured dominance threshold).
4. Compute raw decision:
   - `child_in_roi_raw = len(candidates_after_dominance) > 0`
   - `confidence_raw = max(candidate_conf)` or `0.0`
5. Apply temporal stabilizer (`3-of-5`) to produce canonical fields:
   - `child_in_roi`
   - `confidence`
6. Apply warning hold/cooldown logic to produce `warning_device_on`.

## Canonical Fields
- `timestamp_iso` - UTC ISO 8601
- `warning_device_on` - boolean (1/0 in MySQL)
- `child_in_roi` - canonical stabilized boolean (1/0 in MySQL)
- `confidence` - canonical stabilized confidence [0.0, 1.0]
- `latency_ms` - int (ms)
- `scenario` - optional string tag

Optional debug fields (socket payload only):
- `child_in_roi_raw`
- `confidence_raw`

## Event Logging
- Log to MySQL `events` table on state change and heartbeat.
- State change means `child_in_roi` or `warning_device_on` changed from the last logged state.
- If DB is down, inference must continue without crashing.

## Validation Steps
1. Simulate a valid child trigger inside ROI: canonical `child_in_roi` becomes `1`.
2. Simulate outside ROI: canonical `child_in_roi` becomes `0`.
3. Simulate tiny/partial child-like box (< min ratio): raw trigger remains `0`.
4. Verify warning hold and min-toggle interval behavior under rapid flicker.
5. Verify events logging and DB-down tolerance.

## Edge Cases
- Partial bbox overlap with ROI: bottom-center rule is the only inclusion criterion.
- Multiple children in ROI: canonical `warning_device_on = 1`, confidence = max stabilized confidence.
- Near-duplicate overlapping candidates: dominance keeps higher-confidence trigger candidate.
