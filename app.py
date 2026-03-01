import time
from datetime import datetime, timezone

from flask import Flask, render_template, request, jsonify, Response
from flask_socketio import SocketIO

import cv2
import json
from pathlib import Path
from cv_inference import ChildLikeDetector, ROI
from warning_controller import WarningController

MODEL_PATH = r"C:\Users\Acer\Documents\CAPSTONE\web_dashboard_analytics\models\yolov8_childlike_best.pt"
CHILD_CONF = 0.65
SMALL_BBOX_RATIO = 0.35
WARNING_HOLD_SECONDS = 2.0
ROI_PATH = Path("roi_config.json")

# Camera source: URL for IP Webcam, or integer for local webcam index
# Switch between these by commenting/uncommenting:
VIDEO_SOURCE = "http://192.168.1.29:8080/video"   # IP Webcam (Infinix Hot 11s)
# VIDEO_SOURCE = 0                               # Local webcam (DirectShow)

# DB Imports
from db import init_db, insert_event, fetch_events, fetch_analytics_aggregates

app = Flask(__name__)
app.config["SECRET_KEY"] = "dev-secret"
# cors_allowed_origins="*" allows the frontend to connect from different ports
# This is crucial for local dev where frontend might be served differently (though here it's same origin)
socketio = SocketIO(app, cors_allowed_origins="*", async_mode="threading")

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
    Sends a minimal camera-off status so the dashboard shows initial state.
    """
    print("Client connected")
    # Emit a minimal "idle" status — no mock data, just safe defaults
    idle_payload = {
        "timestamp_iso": datetime.now(timezone.utc).isoformat(),
        "child_in_roi": False,
        "roi_status": "CLEAR",
        "confidence": 0.0,
        "latency_ms": 0,
        "warning_device_on": False,
        "source": "idle",
        "camera_status": "OFF"
    }
    socketio.emit("status_update", idle_payload)

# --------------------------------------------------------------------------------
# API Routes
# --------------------------------------------------------------------------------

@app.route("/video_feed")
def video_feed_route():
    overlay = request.args.get("overlay", "1") == "1"  # ON by default
    source_uri = request.args.get("source", "")
    return Response(gen_frames(overlay=overlay, source_str=source_uri), mimetype="multipart/x-mixed-replace; boundary=frame")

def gen_frames(overlay=True, source_str=""):
    det = ChildLikeDetector(
        MODEL_PATH,
        conf_child=CHILD_CONF,
        small_bbox_ratio=SMALL_BBOX_RATIO
    )
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

    # --- DB Logging State (change-based + heartbeat) ---
    last_logged = {
        "child_in_roi": None,
        "warning_device_on": None,
        "last_log_time": 0.0
    }
    LOG_HEARTBEAT_SEC = 10.0  # heartbeat every 10 seconds while camera is running

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

            # --- DB Logging: change-based + heartbeat ---
            try:
                should_log = False

                # Log on meaningful state changes
                if (out["child_in_roi"] != last_logged["child_in_roi"] or
                    warning_device_on != last_logged["warning_device_on"]):
                    should_log = True

                # Heartbeat: ensure at least one log every N seconds while running
                if (now - last_logged["last_log_time"]) >= LOG_HEARTBEAT_SEC:
                    should_log = True

                if should_log:
                    # Enrich payload with all fields insert_event() requires
                    db_payload = {
                        "timestamp_iso": out["timestamp_iso"],
                        "source": "yolo",
                        "child_in_roi": out["child_in_roi"],
                        "roi_status": out["roi_status"],
                        "confidence": out["confidence"],
                        "latency_ms": out["latency_ms"],
                        # Derived / contract fields
                        "warning_logic_on": out["child_in_roi"],  # MUST equal child_in_roi
                        "switch_enabled": True,                   # hardware switch — always on for now
                        "warning_device_on": warning_device_on,
                        # Power — no hardware yet, use honest defaults
                        "battery_percent": 0.0,
                        "solar_status": "N/A",
                        # Context
                        "scenario": "Live",
                        "camera_status": "OK",
                        "edge_status": "OK",
                        "led_driver_status": "Ready"
                    }
                    insert_event(db_payload)

                    # Update tracking state
                    last_logged["child_in_roi"] = out["child_in_roi"]
                    last_logged["warning_device_on"] = warning_device_on
                    last_logged["last_log_time"] = now
            except Exception as e:
                print(f"[LIVE] DB logging error: {e}")

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

    # Run the Flask-SocketIO server (no mock thread — real data only)
    socketio.run(app, host="0.0.0.0", port=5000, debug=True, allow_unsafe_werkzeug=True)
