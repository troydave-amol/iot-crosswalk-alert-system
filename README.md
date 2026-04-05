# Smart Crosswalk Analytics Dashboard

Repository snapshot updated for April 5, 2026.

This project is the working dashboard and backend for the IoT-Based Smart School-Zone Crosswalk Alert System. The current repo is no longer just a "manual dataset reset" scaffold. It already contains a live Flask + Socket.IO dashboard, Hikvision RTSP support, MP4 video-test mode, MySQL-backed logs and analytics, a trained YOLO checkpoint, and archived dataset/training artifacts.

## What Is In The Repo Right Now

- A Flask application in `app.py` that serves the dashboard, MJPEG stream, ROI APIs, camera status APIs, event logs, analytics, and mode switching.
- A YOLO inference wrapper in `cv_inference.py` that applies ROI-gated detection, dominance filtering, and emits raw detector state.
- Runtime smoothing in `detection_tracker.py` and `warning_controller.py`:
  - IoU-based box tracking
  - 3-of-5 temporal vote stabilization
  - warning hold and anti-chatter toggle control
- A MySQL persistence layer in `db.py` for event inserts, filtered log queries, and aggregate analytics.
- A trained checkpoint at `models/yolov8n_crosswalk_v2_1111_frames.pt`.
- Dataset and training artifacts under `datasets/`, including:
  - `datasets/01_label_studio_exports/`
  - `datasets/02_yolo_dataset/`
  - `datasets/03_training_runs/run_2026_04_03_merged_v2/`
  - `datasets/04_raw_frames_backup/`
- Three demo videos under `test_videos/` for video-test mode.

## Core Dashboard Behavior

- Live mode reads a Hikvision RTSP stream when `HIKVISION_RTSP_URL` is configured.
- Video-test mode can upload and replay local `.mp4` files through the same detection pipeline.
- ROI is configured from the Settings page and persisted in `roi_config.json`.
- The app emits `status_update` payloads over Socket.IO and stores state changes plus heartbeat rows in MySQL.
- Logs, analytics, and report views all read from server-side API responses instead of browser-only calculations.

## Run The App

1. Open a terminal in the project folder.
   ```powershell
   cd c:\Users\Acer\Documents\CAPSTONE\web_dashboard_analytics
   ```
2. Activate the virtual environment.
   ```powershell
   .\venv\Scripts\activate
   ```
3. Install dependencies.
   ```powershell
   pip install -r requirements.txt
   pip install numpy opencv-python ultralytics
   ```
4. Confirm the environment variables in `.env` are correct for your machine.
   - `HIKVISION_RTSP_URL` for live camera mode
   - `MODEL_PATH` for the YOLO checkpoint
   - `DB_HOST`, `DB_USER`, `DB_PASS`, `DB_NAME` for MySQL
5. Start the backend.
   ```powershell
   python app.py
   ```
6. Open `http://127.0.0.1:5000`.

## Important Runtime Notes

- `app.py` falls back to `models/manual_crosswalk_detector.pt` only when `MODEL_PATH` is not set. In the current repo, `.env` already points `MODEL_PATH` at `models/yolov8n_crosswalk_v2_1111_frames.pt`.
- The checked-in ROI config is rectangular. The lower-level ROI class is polygon-capable, but the dashboard and API still save rectangular coordinates.
- If the model cannot be loaded, the server should remain up and emit an idle/safe warning state.

## Main API Surface

- `GET /api/health`
- `GET /api/events`
- `GET /api/analytics`
- `GET /api/roi`
- `POST /api/roi`
- `GET /api/camera/status`
- `POST /api/camera/reconnect`
- `GET /api/mode`
- `POST /api/mode/live`
- `POST /api/mode/video_test`
- `GET /api/test_videos`
- `POST /api/test_videos/upload`

Detailed contracts live in:

- `docs/specs/api_events_contract.md`
- `docs/specs/api_analytics_aggregates.md`
- `docs/specs/roi_logic_and_trigger_rules.md`

## Data And Training Assets

- `datasets/02_yolo_dataset/data.yaml` currently defines `names: ['adult', 'child']`.
- The archived training run under `datasets/03_training_runs/run_2026_04_03_merged_v2/` reached:
  - precision: `0.96731`
  - recall: `0.89794`
  - mAP50: `0.96745`
  - mAP50-95: `0.74197`
- The currently stored checkpoint in `models/` appears to be copied from that training lineage.

## Useful Scripts

These scripts are currently safe to rely on:

- `python scripts/validate_labels.py --dataset <dataset_name>`
- `python scripts/split_dataset.py --dataset <dataset_name>`
- `python scripts/smoke_test_api.py --host http://localhost:5000`

These scripts need cleanup before being treated as current:

- `scripts/offline_validation.py`
  - broken by the current ROI constructor/API drift
- `scripts/test_infer_video.py`
  - fails when run from `scripts/` because root imports are not adjusted
- `scripts/verify_db.py`
  - still queries `created_at` and expects `avg_latency_ms`, which no longer match `db.py`
- `test_backend.py`
  - behaves like a live integration script, not an isolated unit test

## Current Repo Inconsistencies To Know About

- Class-index mismatch:
  - `app.py` and `cv_inference.py` currently treat class `1` as the child class at runtime.
  - `scripts/setup_datasets.py` and `scripts/split_dataset.py` still emit YAML with `0: child_like` and `1: adult_like`.
  - `datasets/02_yolo_dataset/data.yaml` instead uses `['adult', 'child']`.
- ROI API drift:
  - `cv_inference.ROI` now works as a polygon-first object.
  - older tests and scripts still call `ROI(x1=..., y1=..., x2=..., y2=...)` or `ROI(0, 0, ...)`.
- Dependency gap:
  - `requirements.txt` currently covers the web stack but not the OpenCV, Ultralytics, or NumPy runtime dependencies imported by the CV pipeline.
- Legacy path assumptions:
  - several helper scripts still reference older dataset paths such as `merged_v2`, `merged_dataset_v1`, or `afternoon_v1`.

## Documentation Map

- `docs/project_overview.md` - current architecture and repo status
- `docs/specs/` - API, ROI, training, dataset, and annotation references
- `docs/assistants/` - guidance files for AI-assisted work in this repo
