# Capsone Project Overview & System Context

**Project Title:** Smart Crosswalk Alert System for Real-Time Child Detection
**Purpose of this Document:** This Markdown file serves as the definitive architecture, context, and foundational guide for the Capstone Project. It is designed to immediately bring AI assistants up to speed on the system's goals, tech stack, and logic parameters whenever a new chat is initialized.

---

## 1. Project Objective and Real-World Application

The primary objective of this capstone is to enhance pedestrian safety at crosswalks, distinctly focusing on **children**. Children are at a higher risk of roadside accidents due to their size, unpredictable movements, and lack of traffic awareness. 

This system utilizes high-definition IP Cameras (typically Hikvision CCTV over RTSP) mounted near a crosswalk. By utilizing an advanced Machine Learning engine (YOLOv8), the system dynamically scans the video feed. When a **child** steps into a pre-defined virtual "Region of Interest" (ROI) on the street, the system triggers a physical/audio **Warning Device** (like a flashing beacon or siren) to immediately alert incoming vehicular traffic. Adults in the same zone do not trigger the same extreme warning response, isolating the alert for high-risk demographic protection.

---

## 2. Core Operational Modules

The project is divided into tightly integrated modules managed through a centralized Python/Flask backend and a real-time web dashboard.

### A. Web Dashboard & Analytics UI (Frontend)
- **Files:** `templates/index.html`, `static/css/dashboard.css`, `static/js/dashboard.js`
- **Function:** Serves as the administrative control center. Users monitor the Live Surveillance Feed, track the AI engine's real-time latency, modify system settings, and review statistical charts.
- **Tech Stack:** Vanilla HTML/CSS/JS, Socket.IO (for real-time `mode_update` and frame streaming), Chart.js (for rendering metrics).

### B. Flask Control Server & WebSockets (Backend)
- **Files:** `app.py`
- **Function:** The heartbeat of the system. It provisions the HTTP REST APIs, hosts the Socket.IO server, initializes background capture threads for OpenCV, and coordinates all sub-modules. It is responsible for serving both `Live CCTV Mode` and `Video Test Mode` (allowing simulated runs using local `.mp4` datasets).

### C. Artificial Intelligence & Computer Vision Pipeline
- **Files:** `cv_inference.py`, `models/yolov8n_crosswalk_v2_1111_frames.pt`
- **Function:** Runs the custom-trained YOLOv8 model. The logic strictly detects bounding boxes in a frame, identifies the class (`0: adult`, `1: child`), calculates a confidence score, and checks spatial constraints.
- **ROI Logic:** Uses `roi_config.json` to draw a polygonal Region of Interest. Detections only matter if the subject's feet (bottom of the bounding box) overlap within this ROI polygon inside the image.

### D. Stabilization & Tracking (False-Positive Prevention)
- **Files:** `detection_tracker.py`, `warning_controller.py`
- **Function:** In the real world, AI models experience "flicker" (a detected object disappearing for a split second due to lighting or occlusion). The tracker assigns temporal IDs to bounding boxes via Intersection-over-Union (IoU) logic. The Warning Controller ensures the physical alarm is only triggered using a steady buffer protocol (e.g., waiting for consistently positive frames before emitting the trigger) to prevent erratic hardware switching.

### E. Database & Logging Analytics
- **Files:** `db.py`
- **Function:** An SQLite/MySQL controller responsible for maintaining extensive event logs. Whenever a child triggers the warning, a detailed database row is written. This allows the dashboard to generate reports, historical aggregations, and traffic metrics over set timelines (e.g., "15m", "1h", "today").

---

## 3. Technology Stack Summary

- **Object Detection:** YOLOv8 (PyTorch base), OpenCV (cv2)
- **Backend Frame Serving:** Python 3, Flask, Flask-SocketIO (Eventlet / threading)
- **Frontend SPA:** Vanilla JS, DOM manipulation, FontAwesome Icons, Chart.js
- **Data Persistence:** Relational Database (SQL via Python `sqlite3`/MySQL wrappers)
- **Camera Ingestion:** FFMPEG optimization flags alongside `cv2.VideoCapture` via RTSP streaming

---

## 4. Key Developer Constraints & Rules for AI

1. **Zero Logic Destructivity:** When upgrading the User Interface, you must maintain all pre-existing javascript IDs (e.g., `#live-child`, `#live-latency`, `liveCam`). The Python socket logic explicitly drives data to these specific DOM hooks.
2. **Custom CSS Emphasis:** The dashboard operates without massive libraries like Tailwind; it relies heavily on bespoke properties in `dashboard.css`. Maintain modern, premium web aesthetics (glassmorphism, subtle shadows, deep contrast).
3. **Threading Caveats:** OpenCV camera capturing is highly blocking. All streaming and AI inference occur in isolated background threads to prevent the Flask REST API from freezing.
4. **Classes:** Ensure the runtime inference engine adheres strictly to `class 1` representing the child demographic.

By reading this document, any AI assistant stepping into this workspace has the exact mental schematic of the system to provide accurate, context-aware debugging, architectural advice, and code generation.
