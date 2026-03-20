# Crosswalk Safety Dashboard

Dashboard and backend for the IoT-Based Smart School-Zone Crosswalk Alert System.

## Current Phase

As of March 20, 2026, the active project has been reset to a manual-dataset workflow.

- Legacy external datasets are no longer part of the active repo workflow.
- The previous trained child-detection model is no longer treated as valid.
- The app now stays in a safe idle state until a new manual-model weight file is supplied.

## Run the App

1. Open a terminal in the project folder:
   ```powershell
   cd c:\Users\Acer\Documents\CAPSTONE\web_dashboard_analytics
   ```
2. Activate the virtual environment:
   ```powershell
   .\venv\Scripts\activate
   ```
3. Start the backend:
   ```powershell
   python app.py
   ```
4. Open:
   [http://127.0.0.1:5000](http://127.0.0.1:5000)

## Model Behavior

- Default model location: `models/manual_crosswalk_detector.pt`
- Override with environment variable: `MODEL_PATH`
- If the file does not exist, live view still streams video and ROI overlays, but detection remains `idle` with warning output OFF.

## Manual Dataset Workspace

Run:

```powershell
python scripts/setup_datasets.py
```

That creates the active manual dataset layout under `datasets/site_dataset_v1/`:

- `videos_raw/`
- `frames_raw/`
- `frames_selected/`
- `labels/`
- `exports/`
- `rejected/`

## Dataset Commands

Validate labels in the selected-frame workspace:

```powershell
python scripts/validate_labels.py --dataset site_dataset_v1
```

Build a YOLO train/val/test export:

```powershell
python scripts/split_dataset.py --dataset site_dataset_v1
```

## Live Settings

Default live settings still target smooth streaming:

- `LIVE_CAM_WIDTH=1280`
- `LIVE_CAM_HEIGHT=720`
- `LIVE_YOLO_IMGSZ=640`
- `LIVE_STREAM_FPS=25`
- `LIVE_INFER_INTERVAL_SEC=0.125`

When a new manual model is ready, detection uses:

- `LIVE_CHILD_CONF`
- `LIVE_MIN_CHILD_BBOX_RATIO`
- `LIVE_DOMINANCE_IOU`
- `LIVE_WARNING_HOLD_SECONDS`
- `LIVE_WARNING_MIN_TOGGLE_SEC`
