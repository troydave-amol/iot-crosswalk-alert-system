# System Architecture Reference Manual
**Project Title:** IoT-Based Smart School-Zone Crosswalk Alert System Using CNN for Real-Time Child Pedestrian Detection  
**Repository:** `web_dashboard_analytics`  
**Deployment Target:** Casisang Central School Crosswalk, Barangay Casisang, Malaybalay City, Bukidnon  
**Document Purpose:** Complete ground-truth technical architecture specification for capstone manuscript drafting and formal system architecture diagramming.

---

## 1. Architectural Layers & Block Diagram Specification

This section defines the discrete boxes (components) and arrows (interfaces/protocols) needed to construct a formal System Architecture Block Diagram.

### 1.1 Layer 1: Hardware & Physical Infrastructure

#### Component 1: Hikvision IP CCTV Camera
- **Hardware Profile:** Hikvision IP Camera (`DS-2CD` series) with optical sensor and wide dynamic range (WDR).
- **Physical Location:** Mounted on a dedicated utility pole overlooking the designated pedestrian crosswalk zone outside Casisang Central School.
- **Protocol & Transport:** RTSP over TCP (`rtsp://admin:***@192.168.1.64:554/Streaming/Channels/101`).
- **Data Transmitted:** Continuous H.264/H.265 encoded digital video stream at 1080p resolution (1920×1080) to the Edge Compute host.

#### Component 2: Edge Compute Workstation / Host PC
- **Hardware Profile:** Local edge processing machine (Windows x64 OS, multi-core CPU, optional CUDA GPU acceleration).
- **Runtime Environment:** Python 3 virtual environment (`venv/`), OpenCV 4 with low-latency FFMPEG bindings, Ultralytics YOLOv8 framework, Flask + Eventlet WSGI server, and PyMySQL.
- **Role:** Central computation node running real-time frame ingestion, neural network inference, temporal tracking, decision gating, database management, and web serving.

#### Component 3: ESP32 Microcontroller Unit (MCU)
- **Hardware Profile:** ESP-WROOM-32 32-bit dual-core development board running custom C++ firmware (`esp32_relay/esp32_relay.ino`).
- **Physical Interface:** USB Serial Cable connected to the Edge Compute host (`COM5` at 115200 baud).
- **Logic Level & GPIO:** GPIO 4 configured as active-low digital output driving the relay module. Onboard LED (GPIO 2) provides visual feedback.
- **Bidirectional Serial Protocol:**
  - `Python -> ESP32`: `'1'` (Command: Actuate Relay ON), `'0'` (Command: Deactivate Relay OFF), `'?'` (Heartbeat status query).
  - `ESP32 -> Python`: `"ACK:ON"`, `"ACK:OFF"`, `"STATUS:ON"`, `"STATUS:OFF"`, `"ESP32_RELAY_READY"`.

#### Component 4: 2-Channel Relay Module & Physical Warning Beacon
- **Hardware Profile:** 5V optocoupler-isolated relay module connected to external power circuit.
- **Physical Interface:** ESP32 GPIO 4 connected to Relay IN1 pin; Relay VCC to ESP32 VIN (5V USB); GND to GND.
- **Warning Device:** High-intensity LED pedestrian warning flasher beacons mounted on roadside signage poles facing oncoming vehicular traffic.

#### Component 5: Power Subsystem (Solar & Battery)
- **Design Intent:** Photovoltaic solar panel, 12V deep-cycle battery, and solar charge controller.
- **Current Ground-Truth Status:** Hardware-pending placeholder. The database schema includes `battery_percent` and `solar_status`, currently populated with constant placeholders (`0.0%`, `"N/A"`) until physical telemetry ADC sensors are wired into the serial loop.

---

### 1.2 Layer 2: Software & Backend Architecture

#### Component 1: Central Configuration (`config.py`)
- Reads and parses environment variables from `.env`.
- Exports runtime constants: model path (`models/yolov8n_1500_frames.pt`), inference parameters (`LIVE_CHILD_CONF = 0.65`, `LIVE_MIN_CHILD_BBOX_RATIO = 0.10`, `LIVE_DOMINANCE_IOU = 0.70`, `LIVE_WARNING_HOLD_SECONDS = 3.5`, `LIVE_WARNING_MIN_TOGGLE_SEC = 0.75`), and camera capture properties.
- Computes time-of-day operational windows:
  - 06:00 – 08:30: *Morning School Entry*
  - 11:00 – 13:30: *Mid-Day Shift*
  - 15:30 – 17:00: *Afternoon Dismissal*
  - All other times: *Standard Daylight Ops*

#### Component 2: Session Management & Execution Engine (`services/`)
- **`session_manager.py` (`SessionManager`)**: Singleton controller managing application mode transitions between Live Hikvision CCTV streaming (`LiveSession`) and Video Simulation testing (`VideoTestSession`).
- **`live_session.py` (`LiveSession`)**:
  - *Capture Thread*: Continuous non-blocking OpenCV frame acquisition loop with automatic reconnection logic and frame buffer flushing (`grab()` + `retrieve()`).
  - *Inference Thread*: 8 Hz tick loop executing detector inference, anti-flicker tracking, vote stabilization, warning signal gating, serial relay actuation, and Socket.IO emission.
- **`overlay_renderer.py` (`draw_overlay`)**: Draws visual bounding boxes, confidence score pills, class identifiers, and ROI boundary lines on video frames for dashboard display.
- **`roi_manager.py` (`load_roi_for_frame`)**: Reads quadrilateral polygon coordinates from `roi_config.json` and rescales them dynamically to match current video resolutions.
- **`edge_metrics.py` (`get_edge_compute_metrics`)**: Samples host CPU and RAM utilization percentages using `psutil` throttled with a 1-second cache.

#### Component 3: Computer Vision Inference Engine (`cv_inference.py`)
- **`ROI` Class**: Pre-computes a 2D binary polygon mask (`np.uint8`, shape $H \times W$) for ultra-fast point-in-polygon testing.
  - *5-Point Feet-in-ROI Algorithm*: Extracts the bottom 15% bounding box height ("feet zone") and samples 5 horizontal points ($x = 20\%, 35\%, 50\%, 65\%, 80\%$) against the pre-computed binary mask.
- **`ChildLikeDetector` Class**:
  - Wraps the Ultralytics YOLOv8 nano model (`yolov8n_1500_frames.pt`).
  - Canonical Class Mapping: `Class 0 = adult`, `Class 1 = child` (visually classified based on school-age appearance and body proportions).
  - First-pass execution: `conf = 0.50`, `iou = 0.45`, `agnostic_nms = True`, `imgsz = 640`.
  - Dominance Filtering: Suppresses duplicate overlapping child boxes with $\text{IoU} \ge 0.70$.

#### Component 4: Anti-Flicker Detection Tracker (`detection_tracker.py`)
- **`DetectionTracker` Class**:
  - Spatial Association: Matches bounding boxes across consecutive frames using class-agnostic IoU matching ($\text{IoU} \ge 0.25$).
  - Exponential Moving Average (EMA) Smoothing: Smooths bounding box coordinates ($\alpha = 0.6$) and confidence scores ($\alpha = 0.4$).
  - **15-Frame Hysteresis Class Switching**: Prevents rapid label strobing. A tracked object retains its current class until the detector produces **15 consecutive opposing frames**.
  - Ghost Persistence: Preserves established tracks ($\ge 5$ hits) across brief occlusions (up to 25 missed frames).

#### Component 5: Decision Stabilization & Warning Controller (`warning_controller.py`)
- **`TemporalVoteStabilizer` Class**: Sliding window of 5 frames. Requires at least **3 positive detections out of 5** to assert an active child presence.
- **`WarningController` Class**:
  - Immediate Activation: Transitions warning to ON immediately upon stabilized detection.
  - Hold Timer: Sustains warning ON for **3.5 seconds** after the child exits the ROI to guarantee driver reaction time.
  - Anti-Chatter Protection: Enforces a **0.75-second minimum spacing** between relay state toggles to prevent physical relay bounce.

#### Component 6: Hardware Serial Driver (`hardware_controller.py`)
- **`ESP32Relay` Class**: Thread-safe serial bridge with lazy initialization (connects on first demand to prevent Flask reloader port locks).
- Non-blocking fail-safe: The AI pipeline continues uninterrupted if the ESP32 is physically disconnected.
- Heartbeat Monitor: Sends periodic `'?'` queries every 3 seconds to measure serial round-trip time (RTT) and verify hardware health.

#### Component 7: Web Application & Routing Framework (`app.py`, `routes/`)
- **Flask Application Factory (`create_app`)**: Registers Blueprints and binds Flask-SocketIO.
- **`auth_routes.py`**: Handles user authentication, session creation, password changes, and dynamic routing to role-specific dashboards.
- **`camera_routes.py`**: Generates multi-part MJPEG streams (`/video_feed`) with configurable overlay flags, camera snapshots, and manual reconnection triggers.
- **`events_routes.py`**: Exposes `/api/health`, `/api/events` (paginated filtering), `/api/events/export` (streaming CSV/JSON audit dumps), and `/api/analytics` (server-side aggregate metrics).
- **`mode_routes.py`**: Manages operational switching between Live CCTV and Video Simulation (`.mp4` uploads).
- **`roi_routes.py`**: Exposes JSON REST endpoints for retrieving and updating the 4-point ROI polygon.

#### Component 8: Data Access Repository Layer (`repositories/`, `db.py`)
- **`event_repository.py` (`EventRepository`)**: Executes parameterized SQL queries on the `events` table for insertion, pagination, multi-attribute filtering, and session-wide aggregate calculations.
- **`user_repository.py` (`UserRepository`)**: Manages credential lookup, PBKDF2 password hashing, and user authentication against the `users` table.

---

### 1.3 Layer 3: Database Storage Architecture (MySQL: `crosswalk_db`)

```
+-----------------------------------------------------------------------------------+
|                                  crosswalk_db                                     |
+-----------------------------------------+-----------------------------------------+
|                 users                   |                 events                  |
+--------------------+--------------------+--------------------+--------------------+
| id                 | INT AUTO_INCREMENT | id                 | INT AUTO_INCREMENT |
| username           | VARCHAR(64) UNIQUE | timestamp_iso      | DATETIME (INDEX)   |
| password_hash      | VARCHAR(255)       | source             | VARCHAR(16)        |
| role               | ENUM(...)          | child_in_roi       | TINYINT(1) (INDEX) |
| full_name          | VARCHAR(128)       | roi_status         | VARCHAR(16)        |
| created_at         | DATETIME           | confidence         | FLOAT              |
| last_login         | DATETIME           | latency_ms         | INT                |
+--------------------+--------------------+ warning_logic_on   | TINYINT(1)         |
                                          | switch_enabled     | TINYINT(1)         |
                                          | warning_device_on  | TINYINT(1) (INDEX) |
                                          | child_count        | INT                |
                                          | battery_percent    | FLOAT              |
                                          | solar_status       | VARCHAR(16)        |
                                          | scenario           | VARCHAR(32)        |
                                          | camera_status      | VARCHAR(16)        |
                                          | edge_status        | VARCHAR(16)        |
                                          | led_driver_status  | VARCHAR(16)        |
                                          | capture_ts         | VARCHAR(32)        |
                                          | warning_ts         | VARCHAR(32)        |
                                          +--------------------+--------------------+
```

#### Table: `users`
- Stores system operators and administrators for Role-Based Access Control (RBAC).
- `role`: Enum values `'tmc_officer'` or `'it_specialist'`.
- Passwords stored using secure cryptographic hashes (`pbkdf2:sha256`).

#### Table: `events`
- Records sensor telemetry, detection outputs, and physical warning actuations.
- Events are logged on state transitions (`child_in_roi` or `warning_device_on` changes) or during 10-second periodic heartbeats.
- `capture_ts` and `warning_ts` store microsecond-precision ISO timestamps for the 3-point latency pipeline.

---

### 1.4 Layer 4: Real-Time WebSocket Layer (Socket.IO)

- **`status_update` (Server -> Dashboard, ~8 Hz)**:
  - Broadcasts live telemetry containing: `child_in_roi` (stable bool), `child_in_roi_raw`, `confidence` (stable float), `confidence_raw`, `latency_ms` (YOLO inference time), `stream_latency_ms` (camera-to-inference transport time), `fps`, `frame_drop_rate`, `latency_breakdown` (3-point timestamps and monotonic deltas: $\Delta t_{\text{infer}}$, $\Delta t_{\text{warning}}$, $\text{Total } E2E$), `edge_compute` (CPU%, RAM%), and `relay_status` (connected, heartbeat status, COM port).
- **`camera_status` (Server -> Dashboard)**:
  - Pushes camera stream connectivity status (`connected`, `fps`, `reconnect_attempts`).
- **`mode_update` (Server -> Dashboard)**:
  - Notifies dashboards of operational mode switches (`live` vs. `video_test`) and active video filename.
- **`roi_updated` (Server -> Dashboard)**:
  - Broadcasts newly saved ROI polygon coordinates to all connected clients.
- **`connect` (Client -> Server)**:
  - Client joins role-based room (`role_tmc_officer` or `role_it_specialist`) and receives initial telemetry payload.

---

### 1.5 Layer 5: Frontend & Application Layer

```
                        +------------------------------------+
                        |            Landing Page            |
                        |      (templates/landing.html)      |
                        +-----------------+------------------+
                                          | POST /api/login
                                          v
                        +------------------------------------+
                        |         Role-Based Router          |
                        |          (/dashboard)              |
                        +--------+------------------+--------+
                                 |                  |
           role == "tmc_officer" |                  | role == "it_specialist"
                                 v                  v
    +------------------------------------+  +------------------------------------+
    |       TMC Officer Dashboard        |  |      IT Specialist Dashboard       |
    |   (templates/tmc_dashboard.html)   |  |   (templates/it_dashboard.html)    |
    +------------------------------------+  +------------------------------------+
    | • Live View (#live)                |  | • System Status (#live)            |
    | • Analytics (#analytics)           |  | • Data Logs (#logs)                |
    | • Reports (#reports)               |  | • Model Accuracy (#analytics)      |
    | • ROI Setup (#settings)            |  +------------------------------------+
    +------------------------------------+
```

#### 1. TMC Officer Dashboard (`/dashboard/tmc`)
- **Live View (`#live`)**: Displays live MJPEG stream (`/video_feed`), status pills, warning state, and Video Simulation panel (`POST /api/mode/video_test`, `/api/test_videos`).
- **Analytics (`#analytics`)**: Operational traffic analysis. Stat cards (Total Warnings, Total Detections, Avg Latency, Peak Hour), hourly distribution bar charts, School-Zone Operational Windows donut chart, and Detection-to-Warning Conversion Rate comparative horizontal bar chart (`#chartConversion`).
- **Reports (`#reports`)**: Official printable traffic audit report with institutional letterhead, summary metrics, conversion rate insights, and CSV/JSON download exports.
- **ROI Setup (`#settings`)**: Full-featured interactive HTML5 canvas allowing operators to capture live camera snapshots (`/api/camera/snapshot`), draw/drag a 4-point quadrilateral polygon, and save coordinates (`POST /api/roi`).

#### 2. IT Specialist Dashboard (`/dashboard/it`)
- **System Status (`#live`)**: Diagnostic metrics (AI latency, stream latency, frame drop rate, FPS), Edge Compute telemetry (CPU% and RAM% gauges), ESP32 hardware connection status, and camera reconnect button (`POST /api/camera/reconnect`).
- **Data Logs (`#logs`)**: High-density historical audit table with multi-parameter filtering (time range presets, year/month selectors, warning-only, in-ROI-only, confidence threshold, scenario filter) and full dataset streaming exports (`GET /api/events/export`).
- **Model Accuracy & Diagnostics (`#analytics`)**: Visualizes AI inference latency (average vs. peak), active model deployment verification card (`yolov8n_1500_frames.pt`), and the 3-Point Latency Pipeline Breakdown ($t_1 \rightarrow t_2 \rightarrow t_3$).

---

## 2. Complete End-to-End Data Flow Sequences

### 2.1 Live Detection & Physical Warning Pipeline Flow

1. **Optical Image Ingestion**: The Hikvision CCTV camera captures an optical frame at the Casisang Central School crosswalk and encodes it into an H.264 video packet stream transmitted over RTSP/TCP.
2. **Buffer Ingestion & Capture Timestamp**: `LiveSession._capture_loop()` receives the RTSP stream over Ethernet, discards stale buffered frames via `cap.grab()`, and retrieves the latest frame via `cap.retrieve()`.
   - **Timestamp Recorded**: `capture_ts` ($t_{\text{capture}}$, Point 1) and monotonic clock tick `capture_perf`.
3. **YOLOv8n Neural Inference**: The raw BGR frame is passed to `ChildLikeDetector.infer_frame()`, which executes tensor inference using `yolov8n_1500_frames.pt` ($640 \times 640$).
   - **Timestamp Recorded**: Monotonic clock tick `inference_perf` ($t_{\text{infer}}$, Point 2) and calculation of raw inference latency $\text{latency\_ms}$.
4. **Candidate Extraction & Spatial Feet Gating**:
   - Detections are filtered for Class ID `1` (`child`), confidence $\ge 0.65$, and bounding box height $\ge 10\%$ of frame height.
   - The bottom 15% feet zone of each candidate box is sampled across 5 points and tested against the pre-computed ROI polygon mask (`ROI._mask`).
   - Dominance IoU filtering ($0.70$) removes near-duplicate candidate boxes.
5. **Anti-Flicker Box Tracking & Temporal Smoothing**:
   - `DetectionTracker.update()` matches candidate boxes using IoU spatial association.
   - Applies EMA coordinate and confidence smoothing.
   - Applies 15-frame class hysteresis to suppress label flickering between adult and child classifications.
6. **Temporal 3-of-5 Voting**: `TemporalVoteStabilizer.update()` evaluates the sliding window of 5 frames, requiring $\ge 3$ positive child detections to confirm `child_in_roi_stable = True`.
7. **Warning Decision & Hold Gating**:
   - `WarningController.update()` activates the warning state immediately upon confirmed detection.
   - Sustains the warning for a 3.5-second hold period after the child leaves the ROI.
   - Enforces a 0.75-second minimum interval between toggle events to prevent relay chatter.
   - **Timestamp Recorded**: `warning_ts` ($t_{\text{warning}}$, Point 3) and monotonic clock tick `warning_perf`.
8. **Physical Warning Actuation**: `ESP32Relay.set_state(warning_device_on)` transmits ASCII byte `'1'` (ON) or `'0'` (OFF) over USB Serial (`COM5`, 115200 baud). The ESP32 MCU pulls GPIO 4 LOW, closing the relay and activating the LED warning flasher beacons.
9. **3-Point Latency Measurement**:
   - $\Delta t_{\text{infer}} = (\text{inference\_perf} - \text{capture\_perf}) \times 1000$ (Camera transport to inference completion)
   - $\Delta t_{\text{warning}} = (\text{warning\_perf} - \text{inference\_perf}) \times 1000$ (Inference to warning actuation)
   - $\text{Total } E2E = \Delta t_{\text{infer}} + \Delta t_{\text{warning}}$
10. **Telemetry Broadcast**: `LiveSession` emits the `status_update` payload containing real-time telemetry, edge CPU/RAM metrics, and 3-point latency breakdown over Flask-SocketIO.
11. **Visual Overlay Rendering**: `draw_overlay()` draws bounding boxes, confidence tags, and ROI boundaries on the frame, yielding multi-part JPEG frames to `/video_feed`.
12. **Persistent Event Logging**: If a state change occurs (`child_in_roi` or `warning_device_on`) or during the 10-second heartbeat, `_log_db()` inserts a structured audit row into the MySQL `events` table.

---

### 2.2 Dashboard Data Retrieval & Query Flow

1. **Dashboard Initialization**: Operator opens `/dashboard/tmc` or `/dashboard/it` in a web browser.
2. **WebSocket Handshake**: Socket.IO client connects to Flask-SocketIO (`/socket.io`), is assigned to a role room (`role_tmc_officer` or `role_it_specialist`), and receives initial state payloads.
3. **Live Stream Consumption**: Browser displays live video via an `<img>` tag pointing to `/video_feed?overlay=1`.
4. **Historical Analytics & Report Querying**:
   - Operator selects a time filter (Preset: `today`, `15m`, `1h`, `all`; or Historical: `Year`, `Months`).
   - Client executes asynchronous `fetch()` to `/api/analytics` or `/api/events`.
5. **Database Aggregation**:
   - Route handler verifies session role via `@login_required` / `@role_required`.
   - `EventRepository` executes optimized, indexed SQL aggregation queries on `crosswalk_db.events`.
6. **Data Rendering**: Flask returns JSON responses. Chart.js draws hourly distribution and conversion rate bar charts; DOM scripts populate KPI metric cards and audit log tables.

---

## 3. Comparison with Conceptual Manuscript

The table below outlines the specific architectural evolutions between initial design concepts and the actual operational implementation:

| Architectural Area | Conceptual / Manuscript Proposal | Actual Implemented Codebase |
| :--- | :--- | :--- |
| **User Roles & Dashboards** | Single unified dashboard without role segregation. | Full Role-Based Access Control (RBAC) with MySQL `users` table and two dedicated dashboards: **TMC Officer** (operations, video simulation, reports, ROI) and **IT Specialist** (diagnostics, edge metrics, 3-point latency breakdown, raw logs). |
| **Detection Trigger Logic** | Raw YOLOv8 bounding box immediately toggles hardware relay. | 7-stage stabilization pipeline: YOLOv8n inference $\rightarrow$ candidate filter & 5-point feet zone check $\rightarrow$ dominance suppression $\rightarrow$ IoU tracking & EMA smoothing $\rightarrow$ 15-frame class hysteresis $\rightarrow$ 3-of-5 temporal voting $\rightarrow$ 3.5s hold timer & anti-chatter gating. |
| **Model Classification Truth** | Early drafts assumed biological age estimation (`0: child, 1: adult`). | Canonical runtime truth: Visual classification based on school-age proportions (`0: adult, 1: child`). |
| **Latency Measurement** | Single gross latency figure reported. | Segmented 3-Point Monotonic Latency Pipeline: Point 1 Camera Grab ($t_1$) $\rightarrow$ Point 2 YOLO Inference ($t_2$) $\rightarrow$ Point 3 Warning Decision ($t_3$), measuring transport, inference, and actuation deltas. |
| **Reliability & False Alarms** | Documented a "False Warning Rate" / "False Alarm Rate" metric. | Confirmed structurally non-functional without human ground truth. Replaced with **Detection-to-Warning Conversion Rate** comparative horizontal bar chart and KPI. |
| **Solar / Battery Monitoring** | Depicted as active live telemetry. | Schema includes columns; values are currently software placeholders (`0.0%`, `"N/A"`) awaiting physical charge-controller telemetry integration. |
| **Backend Organization** | Monolithic single-script architecture. | 3-tier modular architecture: Flask Blueprints (`routes/`), business services (`services/`), data repositories (`repositories/`), and centralized configuration (`config.py`). |
