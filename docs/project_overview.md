# Smart Crosswalk Project Overview

Repository state summarized for April 5, 2026.

## Current Baseline

The repo currently contains a working dashboard stack plus archived dataset and training assets. It is not accurate anymore to describe this project as "manual dataset only with no active detector."

What is already present:

- a Flask + Socket.IO dashboard in `app.py`
- live Hikvision RTSP capture and reconnect handling
- MP4 video-test mode with upload and playback from `test_videos/`
- YOLO-based inference in `cv_inference.py`
- anti-flicker box tracking in `detection_tracker.py`
- temporal warning stabilization in `warning_controller.py`
- MySQL event logging and aggregate analytics in `db.py`
- a trained checkpoint in `models/yolov8n_crosswalk_v2_1111_frames.pt`
- merged dataset and archived run outputs under `datasets/`

## Runtime Architecture

### 1. Dashboard and transport

- `templates/index.html`
- `static/js/dashboard.js`
- `static/js/contract.js`
- `static/css/dashboard.css`

The UI exposes five major sections: Live View, Logs, Analytics, Reports, and Settings.

### 2. Inference and warning pipeline

- `cv_inference.py`
  - YOLO inference wrapper
  - ROI feet-zone checks
  - trigger-candidate dominance filtering
- `detection_tracker.py`
  - IoU-based track persistence and EMA smoothing
- `warning_controller.py`
  - 3-of-5 temporal vote stabilization
  - warning hold and minimum toggle interval logic

### 3. Persistence and analytics

- `db.py`
  - database initialization
  - event inserts
  - filtered event retrieval
  - aggregate analytics for `15m`, `1h`, `today`, and `all`

## Operating Modes

### Live mode

- reads the Hikvision RTSP stream
- auto-reconnects when capture fails
- emits live `status_update` payloads
- stores state-change and heartbeat rows in MySQL

### Video-test mode

- reuses the same inference pipeline with an uploaded or preloaded `.mp4`
- exposes available files through `/api/test_videos`
- tags DB rows as `Video Test: <filename>`

## Current Data And Model Assets

- `models/yolov8n_crosswalk_v2_1111_frames.pt`
  - current checkpoint in `models/`
- `datasets/01_label_studio_exports/`
  - zipped label exports
- `datasets/02_yolo_dataset/`
  - current merged YOLO dataset snapshot
- `datasets/03_training_runs/run_2026_04_03_merged_v2/`
  - archived training outputs and plots
- `datasets/04_raw_frames_backup/`
  - raw frame backup material
- `training/train_3_2.0.ipynb`
  - moved notebook artifact under `training/`

## Verification Snapshot

During the documentation refresh, the current repo checked out like this:

- `python -m py_compile app.py cv_inference.py warning_controller.py db.py detection_tracker.py`
  - passed
- `python -m unittest test_detection_stabilization.py`
  - failed because ROI tests still use the older rectangle constructor API
- `python -m unittest test_backend.py`
  - failed immediately because the file is a live integration script that expects a running server at `localhost:5000`
- `python scripts/offline_validation.py`
  - failed because it still uses `ROI(x1=..., y1=..., x2=..., y2=...)`
- `python scripts/test_infer_video.py --help`
  - failed because root imports are not adjusted when run from `scripts/`

## Known Implementation Gaps

### Class-order mismatch

The repo currently disagrees about class IDs:

- runtime inference logic treats class `1` as the child class
- manual dataset scaffold scripts still emit `0: child_like`, `1: adult_like`
- `datasets/02_yolo_dataset/data.yaml` uses `['adult', 'child']`

This must be reconciled before the next export-to-training-to-deployment cycle.

### ROI API drift

- the dashboard still saves a rectangle to `roi_config.json`
- the lower-level ROI object is now polygon-first
- several tests and helper scripts still call the old rectangle constructor directly

### Legacy helper scripts

Some scripts still target older dataset paths such as `merged_v2`, `merged_dataset_v1`, or `afternoon_v1`. Treat those as historical until they are updated.

### Dependency documentation gap

`requirements.txt` currently covers the web stack only. The runtime CV stack also needs NumPy, OpenCV, and Ultralytics.

## Near-Term Priorities

- reconcile class IDs across training data, docs, and runtime inference
- normalize ROI helper usage around one supported constructor/API
- refresh or retire legacy validation scripts
- verify dataset YAML split paths before the next training run
