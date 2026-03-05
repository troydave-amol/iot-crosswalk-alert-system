# Smart Crosswalk Capstone - Easy Guide

Welcome to the **Smart Crosswalk Project**! Imagine you're building a super smart robot whose only job is to watch a crosswalk and light up a warning sign to keep kids safe when they are crossing the street.

This guide will explain what all the files and folders do, how we taught the robot (Artificial Intelligence), and how everything connects to work perfectly!

---

## 1. How the Project is Organized (Folder Structure)

Think of our project folder like a giant Lego kit. Instead of just throwing all the Lego pieces in one box, we organized them into smaller boxes so we always know where things are.

We use a **3-Layer System** to keep our robot perfectly organized:

### The "What to Do" Layer (Like the Instruction Manual)
*   **Folder:** `docs/specs/`
*   **What it is:** These are text files written in Markdown (a simple way to write reports). They act like the "Boss" of the project.
*   **Why it's important:** These files contain the absolute rules. For example, one file says, *"Only turn on the light for kids, not adults, and don't try to guess exactly how old they are."* In adult terms, this is our "Scope Document."

### The "Doing the Work" Layer (Like the Little Construction Workers)
*   **Folder:** `scripts/`
*   **What it is:** These are Python files (code files) designed to do exactly one job perfectly, over and over again. 
*   **Why it's important:** Instead of a human manually sorting thousands of photos, we run a script (like `setup_datasets.py`) to do it perfectly without making spelling mistakes or getting tired.

### The Raw Materials and The Brain
*   **Folder:** `datasets/`
    *   This is where we keep thousands of pictures and videos of streets, cars, and people. It's the "textbooks" our robot reads to learn what a crosswalk looks like.
*   **Folder:** `models/`
    *   This is the robot's actual "Brain." After the robot studies the textbooks, it saves the things it learned here as a special file (like `yolov8_childlike_best.pt`). If we turn the robot off and back on, it loads this brain file so it doesn't forget anything.
*   **Folder:** `runs/`
    *   This is the robot's "Report Card." It holds graphs and test scores showing us how accurate the robot is.

### The "Face" of the Robot (The Dashboard)
*   **File:** `app.py`
    *   This is the main control room! It creates the website (dashboard) you look at in your web browser. It talks to the database to save history and streams the live video.
*   **File:** `cv_inference.py`
    *   This is the robot's "Eyeballs." It uses the brain (`models/`) to look at the live video and furiously draw little invisible boxes around anyone that looks like a child.
*   **File:** `warning_controller.py`
    *   This is the "Light Switch". If the eyeballs see a child stepping into the crosswalk, this file physically flips the warning switch to "ON". Crucially, it leaves the light on for 2 extra seconds *after* the child leaves, just to be super safe.
*   **File:** `db.py`
    *   This is the "History Book." Every time the warning light turns on or off, it grabs a pen and writes down the exact time it happened in our database (MySQL) so we can look at charts later.

---

## 2. Teaching the Robot (Artificial Intelligence)

Teaching our Artificial Intelligence (AI) was a lot like sending it to school. We did it in two big phases.

### Phase 1: General Pedestrian School 🏫
First, the robot didn't know what a human was. We gave it a massive textbook called the **CityPersons Dataset** (thousands of photos of busy streets). We taught it, *"This moving thing on two legs is a person."* We didn't care if it was a kid or an adult yet, just a person.

### Phase 2: Child Safety Specialty Class 🧒
Once it mastered what a person was, we gave it a harder textbook called the **JAAD Dataset** (videos of people mostly at crosswalks). 

Here is where the strict rules came in. We took a red marker and only circled pedestrians that *looked* like school children. How did we decide?
1.  **Body Size:** Smaller bodies compared to adults.
2.  **Head-to-Body Ratio:** Kids have bigger heads compared to their small bodies.
3.  **School Items:** People wearing backpacks or school uniforms.

If the person looked like an adult, or if they were riding a bicycle, or if they were hiding behind a tree (too hard to see), we told the robot, *"Ignore them!"* 

**The exciting part:** The robot officially graduated Phase 2, and its final smart brain (`models/yolov8_childlike_best.pt`) is fully saved and working!

---

## 3. Is the Robot Ready for a Demo?

**YES! The entire system is working right now like a well-oiled machine.**

Here is exactly what happens when you turn it on (by typing `python app.py` and opening your web browser):

1.  **Opening its Eyes:** The dashboard immediately loads and starts playing a demo video acting as the "Live Camera Feed."
2.  **Activating the Brain:** It loads its smart brain (`models/yolov8_childlike_best.pt`) instantly.
3.  **Watching the Crosswalk:** You will see an invisible "Safe Zone" drawn on the video. This is the **Region of Interest (ROI)**.
4.  **The Trigger Event:** Frame by frame, the robot's eyes scan. If it spots a child, it calculates if they stepped inside the Safe Zone box.
5.  **Flashing the Lights:** As soon as a child steps into the box, the `warning_controller.py` says, **"LIGHTS ON!"** The database writes down the exact millisecond this happened.
6.  **Viewing the History**: If you click the "Logs" or "Analytics" tabs on the dashboard, you instantly see beautiful graphs counting exactly how many times the lights turned on today.

Everything talks to each other perfectly, ensuring kids cross safely and the system logs every successful detection!

Think of ROI as: “Only care about detections inside this rectangle.”

### Correct workflow

1. Go to **Settings → ROI**
2. Use an image that matches your actual camera view:

   * best: take a snapshot from your webcam feed
   * or any still frame from your test video
3. Draw a rectangle **only on the crosswalk area** (where pedestrians will be)
4. Save ROI
5. Go to **Live View**
6. Make sure the place where your “child test content” appears (phone screen or person) is **inside the ROI box**
7. Only then expect `child_in_roi = true`
---

## 4. Current System Status and Progress (As of March 5, 2026)

Big update: our smart crosswalk robot is now much stronger. It is no longer just "detecting boxes". It now works as one complete system from camera input, to AI decision, to warning trigger, to database logging, to dashboard analytics.

### What is already working end-to-end right now

1. Live camera pipeline is running in real time.
2. The AI model loads on app startup and checks each frame for child-like pedestrians.
3. ROI (Region of Interest) is saved in `roi_config.json` and reloaded automatically while the system is running.
4. Warning logic is stabilized using anti-flicker rules:
   - 3-of-5 temporal voting
   - 2-second warning hold
   - 0.75-second minimum toggle gap
5. Socket updates (`status_update`) are sent to dashboard live cards and warning banner/overlay.
6. Events are saved to MySQL with state-change logging plus heartbeat logging.
7. Logs, Analytics, and Reports pages are now DB-backed (not only browser memory).
8. Analytics endpoint computes server-side aggregates for ranges `15m`, `1h`, `today`, and `all`.
9. Report export works in JSON and CSV from server aggregate data.
10. Camera source selection now supports both local USB webcam and optional IP webcam URL.

### Real progress checkpoints already completed

- On March 2, 2026:
  - `runs/detect/retrain_v2/` training run finished.
  - New best weights were copied to `models/yolov8_childlike_best.pt`.
- On March 3, 2026:
  - Live pipeline hardening updates were applied in `app.py`, `cv_inference.py`, and `warning_controller.py`.
- Automated code checks run successfully:
  - `python -m py_compile app.py cv_inference.py warning_controller.py db.py`
  - `python -m unittest test_detection_stabilization.py` (8 tests passed)

### Current model validation snapshot from latest training artifacts

From `runs/detect/retrain_v2/results.csv` (final epoch values):

- Precision: `0.9293`
- Recall: `0.87029`
- F1 Score (computed): `0.8988`
- mAP@0.5: `0.94993`
- mAP@0.5:0.95: `0.67141`

This means the child-like detector is already in a strong state for prototype demonstration.

### Current known limitations (important for honest panel answers)

1. Power telemetry is still prototype-only on dashboard (`Solar`, `Battery`, `LED driver` mostly shown as `N/A` placeholders).
2. Scenario chart depends on scenario tags in DB rows. Current live insertion uses `scenario = "Live"`, so richer scenario comparison needs tagged data collection (Crowded, Night, Rain, etc.).
3. Helper scripts `scripts/verify_db.py` and `scripts/generate_report.py` still use legacy timestamp query fields and should be aligned to current DB schema (`timestamp_iso`) before formal data-audit use.

---

## 5. New Files Added and What They Do

Below are important files now present in the system, and why they matter.

### Core backend and AI flow

- `app.py`
  - Main backend server (Flask + Socket.IO).
  - Handles live streaming, ROI API, camera probing, events API, analytics API, and live status emission.
- `cv_inference.py`
  - YOLO inference wrapper.
  - Applies child-only trigger gates (class, confidence, min size, ROI bottom-center, overlap dominance).
- `warning_controller.py`
  - Temporal stabilizer (`3-of-5`) and warning hold/cooldown logic.
- `db.py`
  - DB initialization, event insertion, filtered event retrieval, and analytics aggregate SQL.
- `roi_config.json`
  - Stores saved ROI coordinates and source image size for scaling.

### Frontend dashboard files

- `templates/index.html`
  - UI layout for Live View, Logs, Analytics, Reports, and Settings.
- `static/js/dashboard.js`
  - Main frontend logic for camera control, live updates, logs filtering, analytics charts, report generation, and ROI tool behavior.
- `static/js/contract.js`
  - Data contract normalization and validation layer for incoming `status_update` payloads.
- `static/css/dashboard.css`
  - Styling and responsive behavior of dashboard.

### API and system contract specs (`docs/specs/`)

- `api_events_contract.md`
  - Canonical event field definitions and endpoint expectations.
- `api_analytics_aggregates.md`
  - Rules for range-accurate analytics aggregates.
- `roi_logic_and_trigger_rules.md`
  - Non-negotiable trigger behavior and ROI decision pipeline.
- `yolov8_training_plan.md`
  - Training strategy, targets, and required evaluation artifacts.
- `annotation_guideline_child_class.md`
  - Child labeling rules (inclusion, exclusion, ambiguity handling).
- `dataset_prepare_citypersons.md`
  - Dataset prep workflow for baseline data.

### Automation and validation scripts (`scripts/`)

- `setup_datasets.py`
  - Dataset setup and YAML generation for baseline phases.
- `split_dataset.py`
  - Deterministic train/val/test split tool.
- `validate_labels.py`
  - YOLO label validation (missing labels, malformed lines, out-of-bounds values).
- `resplit_jaad_childlike_ft.py`
  - Rebuilds fine-tuning split with child-frame prioritization.
- `retrain_childlike_v2.py`
  - Full retrain automation: re-export, re-split, fine-tune, copy best model.
- `test_infer_video.py`
  - Quick inference sanity script on sample video.
- `smoke_test_api.py`
  - API availability and response-shape smoke checks.
- `verify_db.py`
  - SQL-vs-API consistency checker for analytics.
- `generate_report.py`
  - Generates CSV report summaries from DB events.

### Test files

- `test_detection_stabilization.py`
  - Unit tests for detector hardening, IoU dominance behavior, temporal stabilization, and warning hold logic.
- `test_backend.py`
  - Basic ROI API and socket payload test helper.

### Training and model artifacts

- `models/yolov8_childlike_best.pt`
  - Active model used by live app.
- `runs/detect/retrain_v2/`
  - Contains latest training artifacts (`results.csv`, PR/F1 curves, confusion matrix, and weight checkpoints).

---

## 6. How AI Works in Our System (Step by Step, Very Easy)

Think of this as a chain of workers passing one box to the next worker.

1. Camera worker captures a frame.
   - Frame comes from local webcam index or IP camera URL.

2. ROI worker checks safe-zone coordinates.
   - ROI is loaded from `roi_config.json`.
   - ROI is scaled to actual frame size, so saved settings still work even if camera size changes.

3. AI worker (YOLO model) scans the frame.
   - Model finds people-like objects and returns boxes, class IDs, and confidence scores.

4. Child-only filter worker cleans detections.
   - Keep only class `child_like`.
   - Keep only confidence above `LIVE_CHILD_CONF` (default `0.65`).
   - Keep only boxes with enough size (`LIVE_MIN_CHILD_BBOX_RATIO`, default `0.18` of frame height).
   - Keep only boxes whose bottom-center point is inside ROI.

5. Overlap cleaner worker removes near-duplicate child candidates.
   - If 2 child boxes overlap too much (IoU >= `LIVE_DOMINANCE_IOU`, default `0.70`), keep only the stronger one.

6. Raw decision is created.
   - If at least one valid child candidate remains: `child_in_roi_raw = true`.
   - Confidence raw = highest confidence among kept candidates.

7. Temporal stabilizer worker reduces flicker noise.
   - Uses 5-frame window.
   - Needs at least 3 positive frames to declare stable child detection.
   - Output becomes canonical `child_in_roi` and canonical `confidence`.

8. Warning controller worker decides ON/OFF safely.
   - If stable child is inside ROI: warning turns ON.
   - If child leaves ROI: warning stays ON for hold time (`2.0s`) for safety.
   - Fast ON/OFF chatter is blocked by minimum toggle interval (`0.75s`).

9. Live status packet is emitted to dashboard.
   - Backend sends `status_update` using Socket.IO.
   - Dashboard updates cards, warning banner, and overlay in near real time.

10. Visual overlay is drawn on stream.
   - ROI box turns green when clear and red when child detected.
   - Bounding boxes and confidence labels are drawn on frame.

11. Event logger writes meaningful rows to database.
   - Logs when state changes (`child_in_roi` or `warning_device_on`) and every heartbeat interval.

12. Analytics engine summarizes DB data.
   - Computes totals, false warnings, average latency, peak hour, confidence bins, and scenario distribution for selected range.

This is why we can answer panelists confidently: our AI is not one single step. It is a full pipeline with safety filters, stabilization, logging, and analytics.

---

## 7. Key Metrics (Very Easy and Detailed Explanation)

This section is your defense-ready explanation for each metric.

### 1) Latency (ms)

What it means:
- Latency is "how many milliseconds the system needs to process one frame".

In our system:
- Measured in backend per frame (`latency_ms`) around YOLO inference step.
- Dashboard shows current latency in Live View.
- Analytics shows average latency (`avg_latency`) for selected range.

How to explain to panelists:
- "Lower latency means faster response of warning light. If latency is low, warning appears sooner when a child enters ROI."

Simple interpretation:
- Good: consistently low latency.
- Risk: high latency can delay warning activation.

### 2) Confidence (0.0 to 1.0)

What it means:
- Confidence is how sure the AI is that a detected object is a child-like pedestrian.

In our system:
- Raw confidence comes from YOLO.
- We apply threshold `LIVE_CHILD_CONF=0.65`.
- We also show confidence distribution in Analytics (bins from 0.0 to 1.0).

How to explain to panelists:
- "Confidence is the AI certainty score. We only trigger when certainty is high enough and detection is inside ROI."

Simple interpretation:
- Higher confidence usually means stronger detection quality.
- Very low confidence detections are filtered out to avoid noisy triggers.

### 3) Peak Hour

What it means:
- Peak hour is the hour with the highest warning count.

In our system:
- Computed from DB logs by grouping warnings per hour.
- Displayed in Analytics and Reports.
- Presented in local reporting context (Asia/Manila view for dashboard reporting).

How to explain to panelists:
- "Peak hour tells us when risk activity is highest, so traffic managers can focus manpower and monitoring time."

Simple interpretation:
- Useful for operations planning and policy decisions near school zones.

### 4) Precision

What it means:
- Out of all detections that AI said are child-like, how many were correct.

Formula:
- Precision = TP / (TP + FP)

Very easy example:
- If AI said "child" 100 times, and 93 were truly correct, precision is 0.93.

Current model evidence:
- Latest retrain final precision: `0.9293`

How to explain to panelists:
- "Precision answers: when the model says child, how often is it right?"

### 5) Recall

What it means:
- Out of all true child cases in data, how many the AI successfully found.

Formula:
- Recall = TP / (TP + FN)

Very easy example:
- If there were 100 actual child cases and model found 87, recall is 0.87.

Current model evidence:
- Latest retrain final recall: `0.87029`

How to explain to panelists:
- "Recall answers: out of all real child pedestrians, how many did we catch?"

### 6) F1 Score

What it means:
- One score that balances precision and recall.

Formula:
- F1 = 2 * (Precision * Recall) / (Precision + Recall)

Why it matters:
- If precision is high but recall is low, or opposite, F1 reveals that imbalance.

Current model evidence:
- Computed from latest final precision/recall: `0.8988`

How to explain to panelists:
- "F1 is our balance score. It shows the detector is both accurate and reasonably complete."

### 7) Scenario Comparison

What it means:
- Scenario comparison is a count comparison of events per scenario label.

In our system:
- Analytics groups DB rows by `scenario` and shows a bar chart.
- It helps compare where warnings/detections happen more often (example: Live, Crowded, Night, Rain).

Important current-state note:
- Current live insertion mostly tags rows as `Live`, so richer comparison requires data collection with varied scenario tags.

How to explain to panelists:
- "Scenario comparison tells us which operating condition has more warning activity, so we can prioritize improvements in those conditions."

---

If panelists ask "Are these metrics only for AI training or also for real system operation?"
You can answer:
- "Both. Precision, recall, and F1 come from labeled model evaluation. Latency, confidence, peak hour, and scenario comparison come from live system logs and analytics."
