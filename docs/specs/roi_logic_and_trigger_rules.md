# Directive: ROI Logic And Trigger Rules

## Goal

Describe the warning trigger pipeline as it is implemented today, including the current rectangle-based dashboard ROI storage and the newer polygon-capable ROI helper.

## Current ROI Representation

At the dashboard/API layer, ROI is currently stored in `roi_config.json` as:

```json
{
  "x1": 245,
  "y1": 366,
  "x2": 1485,
  "y2": 731,
  "image_w": 1920,
  "image_h": 1080
}
```

At the inference layer, `cv_inference.ROI` is now polygon-first and precomputes a mask for point-in-polygon checks.

Current practical meaning:

- the UI still saves rectangles
- the inference object can support quadrilateral polygons
- several older tests and helper scripts still use the old rectangle constructor style directly

## Warning Trigger Rule

The final warning state should only turn on when the stabilized child-in-ROI state is true.

High-level rule:

- child inside ROI after tracking and stabilization -> `warning_device_on = true`
- no child inside ROI after stabilization and hold expiry -> `warning_device_on = false`

## Actual Runtime Pipeline

### 1. Raw YOLO inference

`ChildLikeDetector.infer_frame()` currently calls Ultralytics with:

- `conf=0.50`
- `iou=0.45`
- `agnostic_nms=True`
- `imgsz=<LIVE_YOLO_IMGSZ>`

### 2. Raw child trigger candidate filter

Current code then filters detections by:

- runtime child class ID expectation
- `conf >= LIVE_CHILD_CONF`
- `bbox_height >= LIVE_MIN_CHILD_BBOX_RATIO * frame_height`
- ROI feet-zone inclusion via `roi.feet_in_roi(...)`

Important note:

- the current runtime treats class `1` as the child trigger class
- some dataset/export scripts still document the opposite class order

## 3. Dominance filter

Near-duplicate trigger candidates are reduced with IoU dominance:

- sort candidates by confidence descending
- suppress lower-confidence candidates whose IoU with a kept box is `>= LIVE_DOMINANCE_IOU`

## 4. Detection tracking

`DetectionTracker` then smooths boxes across frames using:

- IoU matching
- per-track EMA box smoothing
- short-lived ghost persistence through `max_misses`

The ROI decision is recalculated from tracked boxes, not just from the raw detector output.

## 5. Temporal stabilization

`TemporalVoteStabilizer(window_size=5, required_true=3)` converts tracked raw state into the canonical state:

- `child_in_roi`
- `confidence`

## 6. Warning output control

`WarningController` applies:

- immediate enable when stabilized child state becomes true
- warning hold for `LIVE_WARNING_HOLD_SECONDS`
- minimum toggle spacing via `LIVE_WARNING_MIN_TOGGLE_SEC`

## 7. Emission and persistence

On each inference cycle, the live session:

- emits a `status_update` payload over Socket.IO
- draws ROI and detection overlays for the MJPEG stream
- logs DB rows on state change or every 10 seconds as a heartbeat

## Canonical Live Fields

- `timestamp_iso`
- `child_in_roi`
- `child_in_roi_raw`
- `roi_status`
- `confidence`
- `confidence_raw`
- `latency_ms`
- `warning_device_on`

## Current Implementation Caveats

- if ROI loading falls back to the old rectangle constructor path, the current ROI API drift can break tests and helper scripts
- the dashboard persists a rectangle even though the helper class can represent a polygon
- any future ROI tooling work should first normalize on one supported ROI constructor pattern
