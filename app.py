import time
import random
from datetime import datetime, timezone
from threading import Thread

from flask import Flask, render_template, request, jsonify, Response
from flask_socketio import SocketIO

import cv2
import json
from pathlib import Path
from cv_inference import ChildLikeDetector, ROI
from warning_controller import WarningController

MODEL_PATH = r"C:\Users\Acer\Documents\CAPSTONE\web_dashboard_analytics\models\yolov8_childlike_best.pt"
CHILD_CONF = 0.65
WARNING_HOLD_SECONDS = 2.0
DEMO_SOURCE = r"C:\Users\Acer\Documents\CAPSTONE\web_dashboard_analytics\datasets\jaad_source\JAAD\JAAD_clips\video_0005.mp4"
ROI_PATH = Path("roi_config.json")
USE_WEBCAM = True

# Camera source: URL for IP Webcam, or integer for local webcam index
# Switch between these by commenting/uncommenting:
VIDEO_SOURCE = "http://10.0.0.65:8080/video"   # IP Webcam (Infinix Hot 11s)
# VIDEO_SOURCE = 0                               # Local webcam (DirectShow)

# DB Imports
from db import init_db, insert_event, fetch_events, fetch_analytics_aggregates

app = Flask(__name__)
app.config["SECRET_KEY"] = "dev-secret"
# cors_allowed_origins="*" allows the frontend to connect from different ports
# This is crucial for local dev where frontend might be served differently (though here it's same origin)
socketio = SocketIO(app, cors_allowed_origins="*", async_mode="threading")

# --------------------------------------------------------------------------------
# Global System State
# --------------------------------------------------------------------------------
# Holds the current state of the "virtual" edge device.
# Fields match the strict JSON Contract in static/js/contract.js
system_state = {
    # -- Detection & ROI --
    "child_in_roi": False,
    "roi_status": "OUTSIDE",
    "confidence": 0.0,
    "latency_ms": 45,
    
    # -- Warning Logic --
    "warning_logic_on": False,
    "switch_enabled": True,  # Default: Master Switch is ON
    "warning_device_on": False,
    
    # -- Power System --
    "battery_percent": 85.0,
    "solar_status": "Charging",  # "Charging" | "Not charging"
    
    # -- Optional / Context --
    "scenario": "Normal",
    "camera_status": "OK",
    "edge_status": "OK",
    "led_driver_status": "Ready"
}

# --------------------------------------------------------------------------------
# Helper Functions
# --------------------------------------------------------------------------------

def load_roi_for_frame(frame_w: int, frame_h: int) -> ROI:
    """
    Loads ROI saved from Settings ROI tool and scales to current frame size.
    Expected JSON keys: x1,y1,x2,y2,image_w,image_h (pixel coords in saved image space)
    """
    if not ROI_PATH.exists():
        # Safe default: whole frame (but better to require ROI file)
        return ROI(0, 0, frame_w - 1, frame_h - 1)

    data = json.loads(ROI_PATH.read_text(encoding="utf-8"))

    x1, y1, x2, y2 = int(data.get("x1", 0)), int(data.get("y1", 0)), int(data.get("x2", 0)), int(data.get("y2", 0))
    base_w, base_h = int(data.get("image_w", frame_w)), int(data.get("image_h", frame_h))

    sx = frame_w / base_w
    sy = frame_h / base_h

    return ROI(
        x1=int(x1 * sx),
        y1=int(y1 * sy),
        x2=int(x2 * sx),
        y2=int(y2 * sy),
    )

def run_live_inference_loop(socketio):
    det = ChildLikeDetector(MODEL_PATH, conf_child=CHILD_CONF)
    warn_ctrl = WarningController(hold_seconds=WARNING_HOLD_SECONDS)

    cap = cv2.VideoCapture(DEMO_SOURCE)
    if not cap.isOpened():
        print(f"[LIVE] Cannot open source: {DEMO_SOURCE}")
        return

    # Read one frame to get resolution
    ok, frame = cap.read()
    if not ok or frame is None:
        print("[LIVE] Cannot read first frame.")
        cap.release()
        return

    h, w = frame.shape[:2]
    roi = load_roi_for_frame(w, h)

    # rewind for video sources (optional)
    try:
        cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
    except Exception:
        pass

    print(f"[LIVE] Started inference loop @ {w}x{h}, conf={CHILD_CONF}, hold={WARNING_HOLD_SECONDS}s")

    while True:
        ok, frame = cap.read()
        if not ok or frame is None:
            # loop video for demo
            if isinstance(DEMO_SOURCE, str):
                cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
                continue
            break

        out = det.infer_frame(frame, roi)

        # Debounced warning request
        warning_requested = warn_ctrl.update(out["child_in_roi"])

        # For now, since hardware is Step 5.3:
        warning_device_on = bool(warning_requested)

        payload = {
            # frozen contract fields
            "timestamp_iso": out["timestamp_iso"],
            "latency_ms": out["latency_ms"],
            "confidence": out["confidence"],
            "child_in_roi": out["child_in_roi"],
            "roi_status": out["roi_status"],
            "warning_device_on": warning_device_on,
            "source": "yolo"
        }

        print(f"[LIVE] status_update payload: {json.dumps(payload)}")
        socketio.emit("status_update", payload)

        # throttle a bit (prevents CPU spikes)
        socketio.sleep(0.05)  # ~20 updates/sec

def build_status_payload():
    """
    Constructs the payload dictionary strictly adhering to the Data Contract.
    Adds the required timestamp_iso and source metadata.
    Does NOT modify global state.
    """
    payload = system_state.copy()
    # Use UTC to align with DB storage best practices
    payload["timestamp_iso"] = datetime.now(timezone.utc).isoformat()
    payload["source"] = "backend" 
    return payload

def background_status_loop():
    """
    Simulates the Edge AI logic and Hardware IO.
    Runs in a background thread and emits 'status_update' every 1 second.
    """
    print("Background simulation loop started.")
    
    # Simulation counters
    tick = 0
    child_present_timer = 0
    
    # State tracking for logging
    last_logged = {
        "child_in_roi": None,
        "warning_device_on": None,
        "switch_enabled": None,
        "roi_status": None,
        "solar_status": None,
        "battery_percent": -1.0,
        "last_log_time": 0
    }

    while True:
        # --- 1. Simulate Inputs (Child Detection) ---
        # Logic: Randomly trigger a detection event every now and then
        if child_present_timer > 0:
            child_present_timer -= 1
            detected = True
        else:
            detected = False
            # 10% chance to start a detection event if not currently detecting
            # Occurs roughly every 10 seconds on average
            if random.random() < 0.1: 
                child_present_timer = random.randint(3, 8) # Duration: 3-8 seconds
                detected = True

        # --- 2. Update Detection State ---
        system_state["child_in_roi"] = detected
        system_state["roi_status"] = "INSIDE" if detected else "OUTSIDE"
        if detected:
             # High confidence when detected (0.75 - 0.99)
            system_state["confidence"] = round(random.uniform(0.75, 0.99), 2)
        else:
            # Low confidence noise when clear (0.0 - 0.1)
            system_state["confidence"] = round(random.uniform(0.0, 0.1), 2)
            
        system_state["latency_ms"] = random.randint(30, 80)

        # --- 3. Apply Strict Warning Logic (Contract Rules) ---
        
        # Rule 1: warning_logic_on MUST equal child_in_roi
        # simulation of the logic controller's output
        system_state["warning_logic_on"] = system_state["child_in_roi"]
        
        # Rule 2: warning_device_on === (warning_logic_on && switch_enabled)
        # simulation of the physical relay/MOSFET
        system_state["warning_device_on"] = system_state["warning_logic_on"] and system_state["switch_enabled"]

        # --- 4. Simulate Power System ---
        # Logic: Solar charges during "day", drains at "night" or when warning is ON
        # We'll simulate a day/night cycle every 40 ticks
        is_sunny = (tick % 40) < 20 
        
        if is_sunny:
            system_state["solar_status"] = "Charging"
            # Charge up
            system_state["battery_percent"] += 0.5
        else:
            system_state["solar_status"] = "Not charging"
            # Drain
            system_state["battery_percent"] -= 0.2

        # Extra drain if warning light is ON
        if system_state["warning_device_on"]:
            system_state["battery_percent"] -= 0.1

        # Clamp battery 0-100
        system_state["battery_percent"] = max(0.0, min(100.0, round(system_state["battery_percent"], 1)))

        # --- 5. Emit Status Update ---
        payload = build_status_payload()
        
        # broadcast=True is default for emit() but explicit is better
        socketio.emit("status_update", payload)

        # --- 6. Persistent Logging Logic ---
        try:
            should_log = False
            current_time = time.time()
            
            # Check meaningful changes
            if (payload["child_in_roi"] != last_logged["child_in_roi"] or
                payload["warning_device_on"] != last_logged["warning_device_on"] or
                payload["switch_enabled"] != last_logged["switch_enabled"] or
                payload["roi_status"] != last_logged["roi_status"] or
                payload["solar_status"] != last_logged["solar_status"]):
                should_log = True
                
            # Check significant battery change (>= 1.0%)
            if abs(payload["battery_percent"] - last_logged["battery_percent"]) >= 1.0:
                should_log = True

            # Heartbeat force log every 60 seconds
            if current_time - last_logged["last_log_time"] > 60:
                should_log = True

            if should_log:
                insert_event(payload)
                
                # Update last logged state
                last_logged["child_in_roi"] = payload["child_in_roi"]
                last_logged["warning_device_on"] = payload["warning_device_on"]
                last_logged["switch_enabled"] = payload["switch_enabled"]
                last_logged["roi_status"] = payload["roi_status"]
                last_logged["solar_status"] = payload["solar_status"]
                last_logged["battery_percent"] = payload["battery_percent"]
                last_logged["last_log_time"] = current_time

        except Exception as e:
            # Catch-all to ensure logging logic never crashes the status loop
            print(f"Logging Logic Error: {e}")

        
        # Loop delay
        tick += 1
        time.sleep(1)

# --------------------------------------------------------------------------------
# Routes & Events
# --------------------------------------------------------------------------------

@app.route("/")
def index():
    return render_template("index.html")

@app.get("/api/roi")
def api_get_roi():
    if not ROI_PATH.exists():
        return jsonify({"ok": False, "error": "roi_not_set"}), 404
    data = json.loads(ROI_PATH.read_text(encoding="utf-8"))
    return jsonify({"ok": True, "roi": data})

def _validate_roi_payload(d: dict):
    required = ["x1","y1","x2","y2","image_w","image_h"]
    for k in required:
        if k not in d:
            return False, f"missing:{k}", d
    try:
        iw, ih = int(d["image_w"]), int(d["image_h"])
    except Exception:
        return False, "type_error", d

    if iw <= 0 or ih <= 0:
        return False, "bad_image_size", d

    # Clamp coordinates to image bounds (instead of rejecting edge cases)
    x1 = max(0, min(int(round(d["x1"])), iw - 1))
    y1 = max(0, min(int(round(d["y1"])), ih - 1))
    x2 = max(x1 + 1, min(int(round(d["x2"])), iw))
    y2 = max(y1 + 1, min(int(round(d["y2"])), ih))

    # Build clean payload with integer values
    clean = {
        "x1": x1, "y1": y1, "x2": x2, "y2": y2,
        "image_w": iw, "image_h": ih
    }
    return True, "", clean

@app.post("/api/roi")
def api_set_roi():
    d = request.get_json(silent=True) or {}
    ok, err, clean = _validate_roi_payload(d)
    if not ok:
        print(f"[ROI] Validation failed: {err} | payload={d}")
        return jsonify({"ok": False, "error": err}), 400

    ROI_PATH.write_text(json.dumps(clean, indent=2), encoding="utf-8")
    print(f"[ROI] Saved: {clean}")
    socketio.emit("roi_updated", {"roi": clean})
    return jsonify({"ok": True})

live_thread_started = False

@socketio.on("connect")
def handle_connect():
    """
    Triggered when a client connects (dashboard loads or refreshes).
    Sends the immediate state so the dashboard populates instantly.
    """
    print("Client connected")
    payload = build_status_payload()
    socketio.emit("status_update", payload)  # Single emit on connect (fixed duplicate)

    global live_thread_started
    if USE_WEBCAM:
        return  # inference will run inside gen_frames()
    if not live_thread_started:
        live_thread_started = True
        import threading
        t = threading.Thread(target=run_live_inference_loop, args=(socketio,), daemon=True)
        t.start()

# --------------------------------------------------------------------------------
# API Routes
# --------------------------------------------------------------------------------

@app.route("/video_feed")
def video_feed_route():
    overlay = request.args.get("overlay", "1") == "1"  # ON by default
    source_uri = request.args.get("source", "")
    return Response(gen_frames(overlay=overlay, source_str=source_uri), mimetype="multipart/x-mixed-replace; boundary=frame")

def gen_frames(overlay=True, source_str=""):
    det = ChildLikeDetector(MODEL_PATH, conf_child=CHILD_CONF)
    warn_ctrl = WarningController(hold_seconds=WARNING_HOLD_SECONDS)
    last_emit = 0.0
    EMIT_EVERY_SEC = 0.10  # 10 updates/sec

    # 1. Determine local vs IP camera
    if source_str.isdigit():
        video_src = int(source_str)
        # Use DirectShow for local webcams on Windows for faster startup
        cap = cv2.VideoCapture(video_src, cv2.CAP_DSHOW)
        cap.set(cv2.CAP_PROP_FRAME_WIDTH, 1280)
        cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 720)
    elif source_str.startswith("http"):
        video_src = source_str
        cap = cv2.VideoCapture(video_src)
    else:
        # Fallback to configured VIDEO_SOURCE if none provided by frontend
        if isinstance(VIDEO_SOURCE, int):
            cap = cv2.VideoCapture(VIDEO_SOURCE, cv2.CAP_DSHOW)
            cap.set(cv2.CAP_PROP_FRAME_WIDTH, 1280)
            cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 720)
        else:
            cap = cv2.VideoCapture(VIDEO_SOURCE)
        video_src = VIDEO_SOURCE

    if not cap.isOpened():
        print(f"[LIVE] Cannot open video source: {video_src}")
        return

    last_roi_mtime = 0.0
    roi = None
    last_detections = []
    last_child_in_roi = False

    print(f"[LIVE] gen_frames started | source={video_src} | overlay={overlay}")

    while True:
        ok, frame = cap.read()
        if not ok or frame is None:
            time.sleep(0.1)
            continue

        h, w = frame.shape[:2]
        now = time.time()

        # Reload ROI when roi_config.json changes (mtime-based for instant updates)
        try:
            if ROI_PATH.exists():
                m = ROI_PATH.stat().st_mtime
                if m != last_roi_mtime:
                    roi = load_roi_for_frame(w, h)
                    last_roi_mtime = m
                    print(f"[LIVE] ROI reloaded: ({roi.x1},{roi.y1})-({roi.x2},{roi.y2})")
            elif roi is None:
                roi = load_roi_for_frame(w, h)  # default: whole frame
        except Exception as e:
            print(f"[LIVE] ROI reload error: {e}")

        if (now - last_emit) >= EMIT_EVERY_SEC:
            out = det.infer_frame(frame, roi)
            warning_requested = warn_ctrl.update(out["child_in_roi"])
            warning_device_on = bool(warning_requested)
            last_detections = out.get("detections", [])
            last_child_in_roi = out["child_in_roi"]

            payload = {
                "timestamp_iso": out["timestamp_iso"],
                "latency_ms": out["latency_ms"],
                "confidence": out["confidence"],
                "child_in_roi": out["child_in_roi"],
                "roi_status": out["roi_status"],
                "warning_device_on": warning_device_on,
                "source": "yolo"
            }
            socketio.emit("status_update", payload)
            last_emit = now

        # ----- Overlay Drawing -----
        if overlay:
            # A) ROI rectangle — light tint + solid border
            if roi:
                roi_overlay = frame.copy()
                if last_child_in_roi:
                    fill_color = (0, 0, 200)   # Red tint = WARNING
                    border_color = (0, 0, 255)
                else:
                    fill_color = (0, 180, 0)   # Green tint = CLEAR
                    border_color = (0, 255, 0)
                cv2.rectangle(roi_overlay, (roi.x1, roi.y1), (roi.x2, roi.y2), fill_color, -1)
                cv2.addWeighted(roi_overlay, 0.08, frame, 0.92, 0, frame)  # very light tint
                cv2.rectangle(frame, (roi.x1, roi.y1), (roi.x2, roi.y2), border_color, 4)
                # ROI label with background
                roi_label = "ROI: CHILD DETECTED" if last_child_in_roi else "ROI: CLEAR"
                (tw, th), _ = cv2.getTextSize(roi_label, cv2.FONT_HERSHEY_SIMPLEX, 0.8, 2)
                lx, ly = roi.x1, max(th + 10, roi.y1 - 10)
                cv2.rectangle(frame, (lx, ly - th - 6), (lx + tw + 8, ly + 4), (0, 0, 0), -1)
                cv2.putText(frame, roi_label, (lx + 4, ly),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.8, border_color, 2, cv2.LINE_AA)

            # B) Detection bounding boxes
            for d in last_detections:
                x1, y1, x2, y2 = d["bbox"]
                c = d["conf"]
                k = d["cls"]
                if k == 0:  # child_like
                    color = (0, 255, 255)  # Cyan
                    label = f"child_like {c:.2f}"
                    thickness = 3
                else:       # adult_like
                    color = (255, 180, 50)  # Orange
                    label = f"adult_like {c:.2f}"
                    thickness = 2
                cv2.rectangle(frame, (x1, y1), (x2, y2), color, thickness)
                # Label: white text on black background
                (tw, th), _ = cv2.getTextSize(label, cv2.FONT_HERSHEY_SIMPLEX, 0.7, 2)
                cv2.rectangle(frame, (x1, max(0, y1 - th - 8)), (x1 + tw + 6, y1), (0, 0, 0), -1)
                cv2.putText(frame, label, (x1 + 3, max(th + 3, y1 - 3)),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 255, 255), 2, cv2.LINE_AA)

        ret, buffer = cv2.imencode('.jpg', frame)
        if ret:
            frame_bytes = buffer.tobytes()
            yield (b'--frame\r\n'
                   b'Content-Type: image/jpeg\r\n\r\n' + frame_bytes + b'\r\n')

@app.route("/api/health")
def api_health():
    """
    Simple health check.
    Returns 200 OK if server is running.
    """
    return jsonify({"ok": True})

@app.route("/api/events")
def api_events_route():
    """
    Get historical events from DB.
    Returns 503 if DB is unavailable.
    """
    try:
        # Parse Query Params
        range_arg = request.args.get("range", "all")
        limit = int(request.args.get("limit", 50))
        offset = int(request.args.get("offset", 0))
        
        # Boolean flags usually come as strings "true"/"false" or just present
        # Here we assume "true" string for True, anything else False for safety
        warning_only = request.args.get("warning_only", "false").lower() in ("true", "1")
        in_roi_only = request.args.get("in_roi_only", "false").lower() in ("true", "1")
        
        min_conf = float(request.args.get("min_conf", 0.0))
        scenario = request.args.get("scenario", None)
        search = request.args.get("search", None)

        # Enforce max limit
        if limit > 500:
            limit = 500

        data = fetch_events(
            limit=limit,
            offset=offset,
            time_range=range_arg,
            warning_only=warning_only,
            in_roi_only=in_roi_only,
            min_conf=min_conf,
            scenario=scenario,
            search=search
        )
        
        response = {
            "ok": True,
            "total": data["total"],
            "rows": data["rows"]
        }
        return jsonify(response)

    except Exception as e:
        print(f"API EVENTS ERROR: {e}")
        # Return 503 Service Unavailable if DB fails
        return jsonify({"ok": False, "error": "db_unavailable"}), 503

@app.route("/api/analytics")
def api_analytics_route():
    """
    Returns server-side computed analytics aggregates for a given time range.
    Always computes from ALL matching rows in the DB — never limited by page size.
    Timezone: Asia/Manila (UTC+8) for 'today'; UTC rolling windows for '15m' and '1h'.
    """
    try:
        from datetime import timezone as tz_mod, timedelta
        range_arg = request.args.get("range", "all")
        if range_arg not in ("15m", "1h", "today", "all"):
            return jsonify({"ok": False, "error": "invalid_range"}), 400

        agg = fetch_analytics_aggregates(time_range=range_arg)

        # Bin unit label map
        bin_unit_map = {"15m": "1m", "1h": "5m", "today": "1h", "all": "1d"}

        response = {
            "ok": True,
            "range": range_arg,
            "timezone": "Asia/Manila",
            "bin_unit": bin_unit_map.get(range_arg, "1h"),
            "range_start": agg.get("range_start"),
            "range_end": agg.get("range_end"),
            "total_events": agg["total_events"],
            "total_warnings": agg["total_warnings"],
            "total_detections": agg["total_detections"],
            "false_warnings": agg["false_warnings"],
            "avg_latency": agg["avg_latency"],
            "peak_hour": agg["peak_hour"],
            "peak_hour_basis": "warnings",
            "top_scenario": agg.get("top_scenario"),
            "confidence_bins": agg.get("confidence_bins", [0, 0, 0, 0, 0]),
            "scenario_distribution": agg.get("scenario_distribution", []),
            "time_series": agg["time_series"]
        }
        return jsonify(response)

    except Exception as e:
        print(f"API ANALYTICS ERROR: {e}")
        return jsonify({"ok": False, "error": "db_unavailable"}), 503

# --------------------------------------------------------------------------------
# Entry Point
# --------------------------------------------------------------------------------
if __name__ == "__main__":
    # Initialize DB (safe to run multiple times)
    init_db()

    # Start the background simulation thread (DISABLED for live inference mode)
    # t = Thread(target=background_status_loop, daemon=True)
    # t.start()
    
    # Run the Flask-SocketIO server
    socketio.run(app, host="0.0.0.0", port=5000, debug=True, allow_unsafe_werkzeug=True)
