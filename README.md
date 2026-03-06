# Crosswalk Safety Dashboard

Frontend-focused dashboard for the IoT-Based Smart School-Zone Crosswalk Alert System.

## Features
- **Live View**: Real-time YOLO status visualization.
- **Logs**: Event history with filtering and CSV export.
- **Analytics**: Key performance indicators and charts.
- **Reports**: Printable system summary.
- **Settings**: ROI configuration tool (prototype).

## How to Run

1.  **Open Terminal**: Navigate to the project folder:
    ```powershell
    cd c:\Users\Acer\Documents\CAPSTONE\web_dashboard
    ```

2.  **Activate Virtual Environment**:
    ```powershell
    .\venv\Scripts\activate
    ```

3.  **Run Application**:
    ```powershell
    python app.py
    ```

4.  **Access Dashboard**:
    Open your browser and visit:
    [http://127.0.0.1:5000](http://127.0.0.1:5000)

## Configuration
- **Database**: Check `.env` for database settings. If DB is unavailable, API endpoints return `503` and the dashboard shows unavailable-state warnings.

### Live View Performance Profile
- Default live settings now target smooth streaming with decoupled inference:
  - `LIVE_CAM_WIDTH=1280`
  - `LIVE_CAM_HEIGHT=720`
  - `LIVE_YOLO_IMGSZ=640`
  - `LIVE_STREAM_FPS=25`
  - `LIVE_INFER_INTERVAL_SEC=0.125` (about 8 inference updates/sec)
- Confidence threshold guidance:
  - Production: `LIVE_CHILD_CONF=0.65`
  - Sunny-scene testing: `LIVE_CHILD_CONF=0.60`

### Detection Stabilization Defaults
- Inference uses `agnostic_nms=True` with `iou=0.60` to suppress cross-class overlap duplicates.
- Trigger logic uses child detections only (`adult_like` fallback disabled).
- Trigger eligibility requires:
  - `class == child_like`
  - `confidence >= LIVE_CHILD_CONF`
  - `bbox_height >= LIVE_MIN_CHILD_BBOX_RATIO * frame_height` (default `0.18`)
  - bbox bottom-center point inside ROI
- Temporal stabilization uses `3-of-5` voting before warning logic.
- Warning logic keeps `LIVE_WARNING_HOLD_SECONDS=2.0` and anti-chatter `LIVE_WARNING_MIN_TOGGLE_SEC=0.75`.

### Socket Status Debug Fields
- `status_update` keeps canonical fields (`child_in_roi`, `confidence`, `warning_device_on`, etc.).
- Optional debug fields are also emitted:
  - `child_in_roi_raw`
  - `confidence_raw`
