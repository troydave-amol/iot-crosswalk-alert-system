# Crosswalk Safety Dashboard

Frontend-focused dashboard for the IoT-Based Smart School-Zone Crosswalk Alert System.

## Features
- **Live View**: Real-time mock data visualization.
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
- **Database**: Check `.env` for database settings (defaults to strict mock mode if DB unavailable).
- **Mock Mode**: Can be toggled ON/OFF in the dashboard top bar.

### Live View Performance Profile
- Default live settings now target smooth streaming with decoupled inference:
  - `LIVE_CAM_WIDTH=1280`
  - `LIVE_CAM_HEIGHT=720`
  - `LIVE_YOLO_IMGSZ=640`
  - `LIVE_STREAM_FPS=25`
  - `LIVE_INFER_INTERVAL_SEC=0.10` (about 10 inference updates/sec)
- Confidence threshold guidance:
  - Production: `LIVE_CHILD_CONF=0.65`
  - Sunny-scene testing: `LIVE_CHILD_CONF=0.60`
