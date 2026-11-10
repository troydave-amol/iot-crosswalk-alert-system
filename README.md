# IoT-Based Smart School-Zone Crosswalk Alert System

> **A real-time edge computer vision and IoT crosswalk warning system utilizing a custom-trained Convolutional Neural Network (YOLOv8n) to detect child pedestrians and actuate physical roadside alerts in school zones.**

[![Python](https://img.shields.io/badge/Python-3.11-3776AB?logo=python&logoColor=white)](https://www.python.org/)
[![YOLOv8](https://img.shields.io/badge/YOLOv8-Ultralytics-00FFFF?logo=yolo&logoColor=black)](https://github.com/ultralytics/ultralytics)
[![Flask](https://img.shields.io/badge/Backend-Flask%20%2B%20Socket.IO-000000?logo=flask&logoColor=white)](https://flask.palletsprojects.com/)
[![MySQL](https://img.shields.io/badge/Database-MySQL-4479A1?logo=mysql&logoColor=white)](https://www.mysql.com/)
[![Hardware](https://img.shields.io/badge/IoT-ESP32%20Relay%20Bridge-E7352C?logo=espressif&logoColor=white)](https://www.espressif.com/)

---

## 📌 Executive Overview

Pedestrian safety in elementary school zones is a critical public safety challenge. Younger pedestrians are particularly vulnerable at designated crosswalks due to their shorter stature, unpredictable crossing trajectories, and reduced visibility to approaching motorists. Traditional static warning signs and passive flashing yellow beacons operate indiscriminately—frequently ignored by drivers due to alert fatigue.

This project delivers an **intelligent, demand-responsive crosswalk alert system**. Designed for deployment in partnership with municipal traffic authorities (such as the Traffic Management Center of Malaybalay City), the system automatically identifies pedestrians visually exhibiting school-age child characteristics within a designated crosswalk boundary and immediately actuates physical roadside warning beacons to alert oncoming vehicular traffic.

```
+---------------------------------------------------------------------------------------------------------+
|                                        SYSTEM PIPELINE OVERVIEW                                         |
|                                                                                                         |
|   [ Hikvision CCTV / MP4 Simulation ]                                                                   |
|                   │                                                                                     |
|                   ▼                                                                                     |
|   [ YOLOv8n Visual Classifier ]      ──▶ Classifies pedestrians into 'adult' and 'child' appearances    |
|                   │                                                                                     |
|                   ▼                                                                                     |
|   [ Geometric & ROI Polygon Gating ] ──▶ Evaluates foot-zone coordinates inside 4-point crosswalk ROI   |
|                   │                                                                                     |
|                   ▼                                                                                     |
|   [ ByteTrack & Kalman Filter ]      ──▶ Smooths bounding boxes and suppresses transient tracking loss  |
|                   │                                                                                     |
|                   ▼                                                                                     |
|   [ 3-of-5 Temporal Voting Quorum ]  ──▶ Requires 3 positive frames in a 5-frame window (anti-flicker)  |
|                   │                                                                                     |
|                   ▼                                                                                     |
|   [ State Machine Warning Control ]  ──▶ 3.5s hold time & 0.75s anti-chatter transition spacing         |
|                   │                                                                                     |
|         ┌─────────┴─────────────────────────────┐                                                       |
|         ▼                                       ▼                                                       |
|  [ Physical IoT Actuation ]             [ Web Monitoring & Analytics ]                                  |
|  • USB Serial (115200 baud)             • Live 20 FPS MJPEG stream with AI overlay                      |
|  • ESP32 Microcontroller                • Real-time Socket.IO telemetry (latency, FPS, status)          |
|  • Optocoupled Relay Module             • Multi-month trend charts (Chart.js)                           |
|  • High-Intensity Warning Lamp          • MySQL event audit logging & PDF report generation             |
+---------------------------------------------------------------------------------------------------------+
```

---

## 🎯 Key Objectives

1. **Targeted Child Pedestrian Detection:** Detect and categorize pedestrians using a lightweight convolutional neural network trained on localized school-zone CCTV footage, identifying children based on visual appearance, stature, and body proportions.
2. **False Alarm Suppression:** Gate detection triggers through a geometric, polygon-defined Region of Interest (ROI) and a sliding temporal vote window (3 of 5 frames) to eliminate transient noise and background false alarms.
3. **Low-Latency Warning Actuation:** Maintain an edge inference-to-command software latency under 100 ms to switch physical warning beacons well before approaching vehicles reach the crosswalk threshold.
4. **Centralized Municipal Dashboard:** Provide traffic management officers with a centralized monitoring interface featuring live video feeds, real-time telemetry, historical detection analytics, printable activity reports, and interactive ROI calibration.

---

## 🌟 Core Features

### 1. Computer Vision & Detection Pipeline
* **Custom-Trained YOLOv8n Architecture:** Lightweight nano architecture optimized for real-time edge CPU deployment without requiring expensive roadside GPU infrastructure.
* **Appearance-Based Classification:** Distinguishes pedestrians visually categorized as children from adults using stature, bodily proportions, and school uniform cues (*note: visual categorization only; does not estimate biological age*).
* **Calibrated Polygon ROI:** Configurable 4-point perspective polygon matching the crosswalk boundary. Spatial triggers evaluate the pedestrian's **foot-contact zone** rather than upper-body bounding boxes to prevent false triggers from sidewalk foot traffic.
* **Cascaded Association Tracking (ByteTrack + Kalman):** Tracks objects across consecutive frames, smoothing bounding-box jitter and maintaining track continuity during temporary occlusions.
* **Temporal Stabilization:** 5-frame sliding window requiring at least 3 positive detections to confirm a target, eliminating single-frame detection flickers.
* **Anti-Chatter Warning Controller:** Enforces a 3.5-second hold time after a child leaves the crosswalk and mandates a 0.75-second minimum interval between relay toggles to protect electrical components from rapid cycling.

### 2. IoT Hardware Warning Bridge
* **Microcontroller:** ESP32 DevKit V1 connected via high-speed USB serial bridge (115,200 baud).
* **Switching Relay:** 5 V optocoupled relay module providing galvanic electrical isolation between logic circuitry and high-power warning lamps.
* **Fail-Safe Serial Protocol:** Implements command-acknowledgement handshakes (`b'1'` $\rightarrow$ `ACK: ON`, `b'0'` $\rightarrow$ `ACK: OFF`) and periodic heartbeat status queries (`b'?'` $\rightarrow$ `STATUS: ON/OFF`).

### 3. Traffic Management Web Dashboard
* **Live CCTV & Simulation Modes:** Switches seamlessly between live Hikvision RTSP camera streams and prerecorded MP4 video simulation for development, testing, and system verification.
* **Real-Time Telemetry:** Emits millisecond-accurate pipeline latency, inference speeds, frame drop rates, and hardware connection health over WebSockets (Flask-SocketIO).
* **Interactive ROI Configuration:** Visual browser-based canvas allowing municipal operators to click and drag polygon coordinates to calibrate the crosswalk zone without modifying code.
* **Historical Traffic Analytics:** Interactive Chart.js visualizations showing daily warning activations, peak pedestrian crossing hours, and arrival/dismissal period breakdowns.
* **Official Municipal Reports:** Administrative PDF compilation and streaming CSV/JSON audit export with multi-month date and scenario filtering.

---

## 🛠️ Technology Stack

| Layer | Technologies & Tools |
|---|---|
| **Deep Learning & CV** | YOLOv8n (Ultralytics), OpenCV (cv2), PyTorch, NumPy |
| **Backend & APIs** | Python 3.11, Flask, Flask-SocketIO (Eventlet), PySerial, PyMySQL |
| **Database** | MySQL (Database: `crosswalk_db`, Table: `events`) |
| **Frontend Interface** | Vanilla HTML5, Modern CSS3 (Custom Glassmorphism), JavaScript (ES6+), Chart.js, FontAwesome |
| **Embedded / IoT** | ESP32 Microcontroller, Arduino C++ firmware, 5 V Optocoupled Relay Module, High-Intensity LED Warning Beacon |
| **Video Acquisition** | Hikvision High-Definition IP Camera (1080p @ 25 FPS via RTSP) |
| **Data Annotation** | Label Studio (independent human-annotated bounding boxes) |

---

## 📊 Empirical Performance Summary

The system underwent extensive validation across model training, synthetic tracker stress testing, condition-specific evaluations, and operational video processing:

### 1. Model Training & Validation (3,300 Frames, 19,704 Annotations)
* **Dataset:** 33 batches of high-definition footage recorded at Casisang Central School, Malaybalay City (80:20 train/validation split).
* **Mean Average Precision (mAP@50):** **95.97%** at epoch 100; **96.22%** standalone checkpoint validation.
* **Precision / Recall:** **94.36%** precision and **89.69%** recall on the validation set.
* **Peak F1 Score:** **0.92** achieved at confidence threshold 0.498.

### 2. Operational Benchmark (768 Frames, 10 Video Clips)
* **Inference Latency:** Mean **71.33 ms** ($\sigma = 74.21\text{ ms}$, min 48.45 ms) on edge CPU (AMD Ryzen 5 7535HS).
* **Warning-Decision Latency:** Mean **71.89 ms** across all frames; mean **67.60 ms** during active warning events.
* **Consecutive Stream Throughput:** Mean **3.70 FPS** inter-frame cycling rate ($\sigma = 0.76\text{ FPS}$, peak 5.18 FPS).
* **Warning State Toggles:** 35 stable transitions executed with zero rapid-toggle chatter.

### 3. Environmental Condition Evaluation (135 Manually Annotated Frames, 437 Child Instances)
* **Overall Operational Precision (conf = 0.65):** **95.65%** (only 11 false positives across 135 complex frames).
* **Crowded Crosswalk Scenes:** 100.00% precision, 71.01% F1-score (49 of 89 child instances detected; zero false alarms).
* **Partial Occlusion:** 100.00% precision, 84.51% F1-score (30 of 41 child instances detected).
* **Morning Glare / Lens Flare:** 100.00% precision, 73.85% F1-score (24 of 41 child instances detected).
* **Unpredictable Movement:** 99.03% precision, 77.86% F1-score (102 of 159 child instances detected).
* **Strong Shadows (Documented Limitation):** High-contrast asphalt shadows reduce recall to 14.04% (F1: 23.88%), demonstrating the need for supplemental illumination or HDR optics in shadowed settings.

### 4. Physical Relay Command Verification
* **Actuation Success Rate:** **100% (10 of 10 manual command-response trials passed)** with complete serial handshake integrity and physical lamp illumination.

---

## 📂 Repository Structure

```
web_dashboard_analytics/
│
├── app.py                      # Flask application factory and entry point
├── config.py                   # Centralized configuration and .env bindings
├── cv_inference.py             # YOLOv8 inference wrapper, ROI polygon gating, candidate filters
├── detection_tracker.py        # IoU matching, Kalman Filter coordinate smoothing, ByteTrack stage 2
├── warning_controller.py       # 3-of-5 temporal vote stabilizer and warning hold state machine
├── hardware_controller.py      # Non-blocking USB serial bridge for ESP32 relay actuation
├── db.py                       # MySQL database pool, schema initialization, analytics queries
├── roi_config.json             # Active crosswalk polygon vertex coordinates
├── requirements.txt            # Python dependencies
│
├── esp32_relay/
│   └── esp32_relay.ino         # Arduino C++ firmware for ESP32 relay control & serial ACK
│
├── models/
│   └── yolov8n_3300_frames.pt  # Trained YOLOv8n production weights (3,300 frames)
│
├── routes/                     # Modular Flask Blueprints
│   ├── auth_routes.py          # TMC officer authentication and session handling
│   ├── camera_routes.py        # RTSP camera health, reconnect, and MJPEG video feed
│   ├── events_routes.py        # Event logs, CSV/JSON export, and aggregated analytics
│   ├── mode_routes.py          # Operational mode switching (Live vs Video Simulation)
│   └── roi_routes.py           # REST endpoints for fetching and updating ROI coordinates
│
├── services/                   # Background Services & Session Management
│   ├── live_session.py         # Live RTSP processing thread and event loop
│   ├── video_test_session.py   # Video simulation processing loop for MP4 recordings
│   ├── session_manager.py      # Thread-safe coordinator for active video sessions
│   └── camera_health.py        # Background RTSP watchdog and auto-reconnect service
│
├── static/                     # Frontend Assets
│   ├── css/                    # Custom glassmorphic stylesheet (dashboard.css)
│   ├── js/                     # Modular frontend controllers (stream, analytics, reports, roi)
│   └── brand/                  # TMC Malaybalay City logos and UI icons
│
├── templates/                  # Jinja2 HTML Templates
│   ├── login.html              # Secure TMC officer authentication portal
│   ├── index.html              # Main Live View monitoring and simulation dashboard
│   ├── analytics.html          # Historical trends, heatmaps, and school-period charts
│   ├── reports.html            # Printable administrative summary reports
│   └── roi_setup.html          # Interactive canvas for crosswalk polygon calibration
│
├── scripts/                    # Validation, Testing, and Evaluation Utilities
│   ├── run_march2026_evaluation.py   # 768-frame operational latency and throughput benchmark
│   ├── evaluate_condition_groundtruth.py # 135-frame condition-based evaluation runner
│   ├── test_tracker_robustness.py    # 5-condition programmatic unit tests for Kalman tracker
│   └── run_manual_relay_trials.py    # Interactive 10-trial hardware verification utility
│
└── docs/                       # Specifications and Architecture References
    ├── specs/                  # REST API contracts, ROI geometry specs, and database schema
    └── evidence/               # Retained test logs and empirical validation artifacts
```

---

## 🚀 Quickstart Guide

### Prerequisites
* **Operating System:** Windows 10/11 (Development/Deployment Workstation)
* **Python:** Version 3.11 (with `venv`)
* **Database:** MySQL Server 8.0+ (running locally or network-accessible)
* **Hardware (Optional for simulation):** ESP32 DevKit V1 connected via USB and configured on `COM5`

### 1. Clone & Set Up Virtual Environment
```powershell
# Navigate to project directory
cd c:\Users\Acer\Documents\CAPSTONE\web_dashboard_analytics

# Create and activate virtual environment
python -m venv venv
.\venv\Scripts\activate
```

### 2. Install Dependencies
```powershell
pip install --upgrade pip
pip install -r requirements.txt
pip install opencv-python ultralytics numpy pyserial pymysql
```

### 3. Configure Environment Variables
Create or verify your `.env` file in the project root:
```ini
# Application Secrets
SECRET_KEY=dev_secret_key_123
FLASK_APP=app.py
FLASK_ENV=development

# MySQL Database
DB_HOST=127.0.0.1
DB_PORT=3306
DB_USER=root
DB_PASS=
DB_NAME=crosswalk_db

# Detection & Model Configuration
MODEL_PATH=models/yolov8n_3300_frames.pt
LIVE_CHILD_CONF=0.65
LIVE_MIN_CHILD_BBOX_RATIO=0.10
LIVE_DOMINANCE_IOU=0.70
LIVE_WARNING_HOLD_SECONDS=3.5
LIVE_WARNING_MIN_TOGGLE_SEC=0.75

# Live Camera Feed (Hikvision IP Camera)
HIKVISION_RTSP_URL=rtsp://admin:Password@192.168.1.64:554/Streaming/Channels/101
HIKVISION_RECONNECT_SEC=5

# Hardware Warning Bridge (ESP32)
ESP32_ENABLED=true
ESP32_PORT=COM5
ESP32_BAUD=115200
```

### 4. Initialize Database & Launch Application
```powershell
# Start the Flask + Socket.IO server
python app.py
```
Open your web browser and navigate to:
```
http://127.0.0.1:5000
```
* **Default Login:** Use the authorized TMC personnel credentials configured in your user database.
* **Testing without Camera:** In the Live View tab, toggle to **Video Simulation Mode** and select an included test video clip from the test library.

---

## 🔒 Safety, Ethics, and Operational Scope

* **Visual Categorization Disclaimer:** Pedestrian classifications represent visual appearance categories (based on stature, bodily proportions, clothing, and context) learned from annotated training images. The system **does not estimate biological age** and does not perform facial recognition or individual identity tracking.
* **Fail-Safe Design:** If the ESP32 hardware bridge is disconnected or serial communication fails, the Python AI detection pipeline continues running without crashing, recording telemetry and logging events while alerting operators through the dashboard diagnostics.
* **Complementary Traffic Measure:** This system is engineered as an auxiliary warning mechanism to enhance pedestrian awareness. It does not replace standard traffic signs, municipal crossing guards, or traffic laws.

---

## 👥 Project & Institutional Context

* **Project Title:** *IoT-Based Smart School-Zone Crosswalk Alert System Using CNN for Real-Time Child Pedestrian Detection*
* **Stakeholder Partner:** Traffic Management Center (TMC), City Government of Malaybalay
* **Academic Context:** Undergraduate Capstone Project in Computer Engineering / Information Technology (Academic Year 2026)

---

## 📄 License
This repository is developed for academic research, municipal traffic evaluation, and capstone demonstration. All rights reserved by the project researchers and collaborating academic institutions. Commercial utilization or municipal integration requires formal consent.

---

## 📂 Repository Structure

```
web_dashboard_analytics/
│
├── app.py                      # Flask application factory and entry point
├── config.py                   # Centralized configuration and .env bindings
├── cv_inference.py             # YOLOv8 inference wrapper, ROI polygon gating, candidate filters
├── detection_tracker.py        # IoU matching, Kalman Filter coordinate smoothing, ByteTrack stage 2
├── warning_controller.py       # 3-of-5 temporal vote stabilizer and warning hold state machine
├── hardware_controller.py      # Non-blocking USB serial bridge for ESP32 relay actuation
├── db.py                       # MySQL database pool, schema initialization, analytics queries
├── roi_config.json             # Active crosswalk polygon vertex coordinates
├── requirements.txt            # Python dependencies
│
├── esp32_relay/
│   └── esp32_relay.ino         # Arduino C++ firmware for ESP32 relay control & serial ACK
│
├── models/
│   └── yolov8n_3300_frames.pt  # Trained YOLOv8n production weights (3,300 frames)
│
├── routes/                     # Modular Flask Blueprints
│   ├── auth_routes.py          # TMC officer authentication and session handling
│   ├── camera_routes.py        # RTSP camera health, reconnect, and MJPEG video feed
│   ├── events_routes.py        # Event logs, CSV/JSON export, and aggregated analytics
│   ├── mode_routes.py          # Operational mode switching (Live vs Video Simulation)
│   └── roi_routes.py           # REST endpoints for fetching and updating ROI coordinates
│
├── services/                   # Background Services & Session Management
│   ├── live_session.py         # Live RTSP processing thread and event loop
│   ├── video_test_session.py   # Video simulation processing loop for MP4 recordings
│   ├── session_manager.py      # Thread-safe coordinator for active video sessions
│   └── camera_health.py        # Background RTSP watchdog and auto-reconnect service
│
├── static/                     # Frontend Assets
│   ├── css/                    # Custom glassmorphic stylesheet (dashboard.css)
│   ├── js/                     # Modular frontend controllers (stream, analytics, reports, roi)
│   └── brand/                  # TMC Malaybalay City logos and UI icons
│
├── templates/                  # Jinja2 HTML Templates
│   ├── login.html              # Secure TMC officer authentication portal
│   ├── index.html              # Main Live View monitoring and simulation dashboard
│   ├── analytics.html          # Historical trends, heatmaps, and school-period charts
│   ├── reports.html            # Printable administrative summary reports
│   └── roi_setup.html          # Interactive canvas for crosswalk polygon calibration
│
├── scripts/                    # Validation, Testing, and Evaluation Utilities
│   ├── run_march2026_evaluation.py   # 768-frame operational latency and throughput benchmark
│   ├── evaluate_condition_groundtruth.py # 135-frame condition-based evaluation runner
│   ├── test_tracker_robustness.py    # 5-condition programmatic unit tests for Kalman tracker
│   └── run_manual_relay_trials.py    # Interactive 10-trial hardware verification utility
│
└── docs/                       # Specifications and Architecture References
    ├── specs/                  # REST API contracts, ROI geometry specs, and database schema
    └── evidence/               # Retained test logs and empirical validation artifacts
```

---

## 🚀 Quickstart Guide

### Prerequisites
* **Operating System:** Windows 10/11 (Development/Deployment Workstation)
* **Python:** Version 3.11 (with `venv`)
* **Database:** MySQL Server 8.0+ (running locally or network-accessible)
* **Hardware (Optional for simulation):** ESP32 DevKit V1 connected via USB and configured on `COM5`

### 1. Clone & Set Up Virtual Environment
```powershell
# Navigate to project directory
cd c:\Users\Acer\Documents\CAPSTONE\web_dashboard_analytics

# Create and activate virtual environment
python -m venv venv
.\venv\Scripts\activate
```

### 2. Install Dependencies
```powershell
pip install --upgrade pip
pip install -r requirements.txt
pip install opencv-python ultralytics numpy pyserial pymysql
```

### 3. Configure Environment Variables
Create or verify your `.env` file in the project root:
```ini
# Application Secrets
SECRET_KEY=dev_secret_key_123
FLASK_APP=app.py
FLASK_ENV=development

# MySQL Database
DB_HOST=127.0.0.1
DB_PORT=3306
DB_USER=root
DB_PASS=
DB_NAME=crosswalk_db

# Detection & Model Configuration
MODEL_PATH=models/yolov8n_3300_frames.pt
LIVE_CHILD_CONF=0.65
LIVE_MIN_CHILD_BBOX_RATIO=0.10
LIVE_DOMINANCE_IOU=0.70
LIVE_WARNING_HOLD_SECONDS=3.5
LIVE_WARNING_MIN_TOGGLE_SEC=0.75

# Live Camera Feed (Hikvision IP Camera)
HIKVISION_RTSP_URL=rtsp://admin:Password@192.168.1.64:554/Streaming/Channels/101
HIKVISION_RECONNECT_SEC=5

# Hardware Warning Bridge (ESP32)
ESP32_ENABLED=true
ESP32_PORT=COM5
ESP32_BAUD=115200
```

### 4. Initialize Database & Launch Application
```powershell
# Start the Flask + Socket.IO server
python app.py
```
Open your web browser and navigate to:
```
http://127.0.0.1:5000
```
* **Default Login:** Use the authorized TMC personnel credentials configured in your user database.
* **Testing without Camera:** In the Live View tab, toggle to **Video Simulation Mode** and select an included test video clip from the test library.

---

## 🔒 Safety, Ethics, and Operational Scope

* **Visual Categorization Disclaimer:** Pedestrian classifications represent visual appearance categories (based on stature, bodily proportions, clothing, and context) learned from annotated training images. The system **does not estimate biological age** and does not perform facial recognition or individual identity tracking.
* **Fail-Safe Design:** If the ESP32 hardware bridge is disconnected or serial communication fails, the Python AI detection pipeline continues running without crashing, recording telemetry and logging events while alerting operators through the dashboard diagnostics.
* **Complementary Traffic Measure:** This system is engineered as an auxiliary warning mechanism to enhance pedestrian awareness. It does not replace standard traffic signs, municipal crossing guards, or traffic laws.

---

## 👥 Project & Institutional Context

* **Project Title:** *IoT-Based Smart School-Zone Crosswalk Alert System Using CNN for Real-Time Child Pedestrian Detection*
* **Target Deployment Site:** Casisang Central School, National Highway, Barangay Casisang, Malaybalay City, Bukidnon, Philippines
* **Stakeholder Partner:** Traffic Management Center (TMC), City Government of Malaybalay
* **Academic Context:** Undergraduate Capstone Project in Computer Engineering / Information Technology (Academic Year 2026)

---

## 📄 License
This repository is developed for academic research, municipal traffic evaluation, and capstone demonstration. All rights reserved by the project researchers and collaborating academic institutions. Commercial utilization or municipal integration requires formal consent.
