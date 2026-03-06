import os
import threading
import time
from datetime import datetime, timezone
from typing import Dict, Optional, Tuple, Union

from dotenv import load_dotenv
from flask import Flask, render_template, request, jsonify, Response
from flask_socketio import SocketIO

import cv2
import json
from pathlib import Path
from urllib.parse import urlparse, urlunparse
from cv_inference import ChildLikeDetector, ROI
from warning_controller import TemporalVoteStabilizer, WarningController

load_dotenv()

MODEL_PATH = r"C:\Users\Acer\Documents\CAPSTONE\web_dashboard_analytics\models\yolov8_childlike_best.pt"
ROI_PATH = Path("roi_config.json")

def _env_float(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, str(default)))
    except (TypeError, ValueError):
        return float(default)


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, str(default)))
    except (TypeError, ValueError):
        return int(default)


CHILD_CONF = _env_float("LIVE_CHILD_CONF", 0.65)
MIN_CHILD_BBOX_RATIO = _env_float("LIVE_MIN_CHILD_BBOX_RATIO", 0.18)
DOMINANCE_IOU = _env_float("LIVE_DOMINANCE_IOU", 0.70)
WARNING_HOLD_SECONDS = _env_float("LIVE_WARNING_HOLD_SECONDS", 2.0)
WARNING_MIN_TOGGLE_SEC = _env_float("LIVE_WARNING_MIN_TOGGLE_SEC", 0.75)
YOLO_IMGSZ = _env_int("LIVE_YOLO_IMGSZ", 640)
INFER_INTERVAL_SEC = _env_float("LIVE_INFER_INTERVAL_SEC", 0.125)
STREAM_FPS = max(1.0, _env_float("LIVE_STREAM_FPS", 25.0))
CAM_WIDTH = _env_int("LIVE_CAM_WIDTH", 1280)
CAM_HEIGHT = _env_int("LIVE_CAM_HEIGHT", 720)

# Default to local USB webcam for stable, low-latency demo behavior.
# IP webcam remains available via /video_feed?source=http://... from the UI.
VIDEO_SOURCE: Union[int, str] = 0

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

@socketio.on("connect")
def handle_connect():
    """
    Triggered when a client connects (dashboard loads or refreshes).
    Sends a minimal camera-off status so the dashboard shows initial state.
    """
    print("Client connected")
    # Emit a minimal "idle" status with safe defaults.
    idle_payload = {
        "timestamp_iso": datetime.now(timezone.utc).isoformat(),
        "child_in_roi": False,
        "child_in_roi_raw": False,
        "roi_status": "CLEAR",
        "confidence": 0.0,
        "confidence_raw": 0.0,
        "latency_ms": 0,
        "warning_device_on": False,
        "source": "idle",
        "camera_status": "OFF"
    }
    socketio.emit("status_update", idle_payload)

# --------------------------------------------------------------------------------
# Live Pipeline
# --------------------------------------------------------------------------------

def _normalize_ip_camera_source(source_str: str) -> Optional[str]:
    source_clean = (source_str or "").strip()
    if not source_clean:
        return None

    # Allow "192.168.1.29:8080/video" style inputs by assuming HTTP.
    candidate = source_clean
    has_scheme = "://" in candidate
    if not has_scheme:
        candidate = f"http://{candidate.lstrip('/')}"

    try:
        parsed = urlparse(candidate)
        if parsed.scheme in ("http", "https"):
            # Common IP webcam default path.
            if parsed.path in ("", "/"):
                parsed = parsed._replace(path="/video")
            return urlunparse(parsed)
        if parsed.scheme in ("rtsp", "rtmp"):
            return candidate
    except Exception:
        pass

    if has_scheme and candidate.lower().startswith(("http://", "https://", "rtsp://", "rtmp://")):
        return candidate
    return None


def _resolve_video_source(source_str: str) -> Tuple[str, str, Union[int, str]]:
    source_clean = (source_str or "").strip()
    if source_clean.isdigit():
        idx = int(source_clean)
        return f"local:{idx}", "local", idx

    normalized_ip = _normalize_ip_camera_source(source_clean)
    if normalized_ip:
        return f"ip:{normalized_ip}", "ip", normalized_ip

    if isinstance(VIDEO_SOURCE, int):
        return f"local:{VIDEO_SOURCE}", "local", VIDEO_SOURCE

    default_ip = _normalize_ip_camera_source(str(VIDEO_SOURCE))
    if default_ip:
        return f"ip:{default_ip}", "ip", default_ip
    return f"ip:{VIDEO_SOURCE}", "ip", VIDEO_SOURCE


def _draw_overlay(frame, roi: ROI, detections, child_in_roi: bool):
    if roi:
        roi_overlay = frame.copy()
        if child_in_roi:
            fill_color = (0, 0, 200)   # Red tint = WARNING
            border_color = (0, 0, 255)
        else:
            fill_color = (0, 180, 0)   # Green tint = CLEAR
            border_color = (0, 255, 0)
        cv2.rectangle(roi_overlay, (roi.x1, roi.y1), (roi.x2, roi.y2), fill_color, -1)
        cv2.addWeighted(roi_overlay, 0.08, frame, 0.92, 0, frame)
        cv2.rectangle(frame, (roi.x1, roi.y1), (roi.x2, roi.y2), border_color, 4)

        roi_label = "ROI: CHILD DETECTED" if child_in_roi else "ROI: CLEAR"
        (tw, th), _ = cv2.getTextSize(roi_label, cv2.FONT_HERSHEY_SIMPLEX, 0.8, 2)
        lx, ly = roi.x1, max(th + 10, roi.y1 - 10)
        cv2.rectangle(frame, (lx, ly - th - 6), (lx + tw + 8, ly + 4), (0, 0, 0), -1)
        cv2.putText(frame, roi_label, (lx + 4, ly), cv2.FONT_HERSHEY_SIMPLEX, 0.8, border_color, 2, cv2.LINE_AA)

    for d in detections:
        x1, y1, x2, y2 = d["bbox"]
        conf = d["conf"]
        cls = d["cls"]
        if cls == 0:
            color = (0, 255, 255)  # Cyan
            label = f"child_like {conf:.2f}"
            thickness = 3
        else:
            color = (255, 180, 50)  # Orange
            label = f"adult_like {conf:.2f}"
            thickness = 2
        cv2.rectangle(frame, (x1, y1), (x2, y2), color, thickness)
        (tw, th), _ = cv2.getTextSize(label, cv2.FONT_HERSHEY_SIMPLEX, 0.7, 2)
        cv2.rectangle(frame, (x1, max(0, y1 - th - 8)), (x1 + tw + 6, y1), (0, 0, 0), -1)
        cv2.putText(frame, label, (x1 + 3, max(th + 3, y1 - 3)), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 255, 255), 2, cv2.LINE_AA)

    return frame


class LiveSession:
    LOG_HEARTBEAT_SEC = 10.0

    def __init__(self, source_key: str, source_kind: str, source_value: Union[int, str]):
        self.source_key = source_key
        self.source_kind = source_kind
        self.source_value = source_value
        self.viewer_count = 0

        self.detector = ChildLikeDetector(
            MODEL_PATH,
            conf_child=CHILD_CONF,
            min_child_bbox_ratio=MIN_CHILD_BBOX_RATIO,
            dominance_iou=DOMINANCE_IOU,
            imgsz=YOLO_IMGSZ,
        )
        self.stabilizer = TemporalVoteStabilizer(window_size=5, required_true=3)
        self.warn_ctrl = WarningController(
            hold_seconds=WARNING_HOLD_SECONDS,
            min_toggle_interval_sec=WARNING_MIN_TOGGLE_SEC,
        )

        self.cap: Optional[cv2.VideoCapture] = None
        self.stop_event = threading.Event()
        self.state_lock = threading.Lock()
        self.capture_thread: Optional[threading.Thread] = None
        self.inference_thread: Optional[threading.Thread] = None

        self.latest_frame_raw = None
        self.latest_frame_annotated = None
        self.last_roi_mtime = 0.0
        self.roi: Optional[ROI] = None

        self.last_logged = {
            "child_in_roi": None,
            "warning_device_on": None,
            "last_log_time": 0.0,
        }

        self.capture_frames = 0
        self.infer_frames = 0
        self.last_perf_ts = time.time()
        self.last_perf_capture = 0
        self.last_perf_infer = 0

    def start(self):
        self.cap = self._open_capture()
        if not self.cap.isOpened():
            raise RuntimeError(f"Cannot open video source: {self.source_key}")

        self.capture_thread = threading.Thread(target=self._capture_loop, name=f"capture-{self.source_key}", daemon=True)
        self.inference_thread = threading.Thread(target=self._inference_loop, name=f"infer-{self.source_key}", daemon=True)
        self.capture_thread.start()
        self.inference_thread.start()

        print(
            f"[LIVE] Session started | source={self.source_key} | conf_child={CHILD_CONF:.2f} "
            f"| imgsz={YOLO_IMGSZ} | min_bbox_ratio={MIN_CHILD_BBOX_RATIO:.2f} "
            f"| stream_fps={STREAM_FPS:.1f} | infer_interval={INFER_INTERVAL_SEC:.3f}s"
        )

    def stop(self):
        self.stop_event.set()
        if self.capture_thread and self.capture_thread.is_alive():
            self.capture_thread.join(timeout=2.0)
        if self.inference_thread and self.inference_thread.is_alive():
            self.inference_thread.join(timeout=2.0)
        if self.cap is not None:
            self.cap.release()
            self.cap = None
        with self.state_lock:
            self.latest_frame_raw = None
            self.latest_frame_annotated = None
        print(f"[LIVE] Session stopped | source={self.source_key}")

    def get_stream_frame(self, overlay: bool):
        with self.state_lock:
            if overlay and self.latest_frame_annotated is not None:
                return self.latest_frame_annotated
            return self.latest_frame_raw

    def _open_capture(self):
        if self.source_kind == "local":
            cap = cv2.VideoCapture(int(self.source_value))
            cap.set(cv2.CAP_PROP_FRAME_WIDTH, CAM_WIDTH)
            cap.set(cv2.CAP_PROP_FRAME_HEIGHT, CAM_HEIGHT)
            cap.set(cv2.CAP_PROP_FPS, 30)
            return cap

        cap = cv2.VideoCapture(self.source_value)
        cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
        return cap

    def _capture_loop(self):
        while not self.stop_event.is_set():
            if self.cap is None:
                time.sleep(0.02)
                continue
            ok, frame = self.cap.read()
            if not ok or frame is None:
                time.sleep(0.02)
                continue
            with self.state_lock:
                self.latest_frame_raw = frame
            self.capture_frames += 1

    def _refresh_roi(self, frame_w: int, frame_h: int):
        try:
            if ROI_PATH.exists():
                mtime = ROI_PATH.stat().st_mtime
                if self.roi is None or mtime != self.last_roi_mtime:
                    self.roi = load_roi_for_frame(frame_w, frame_h)
                    self.last_roi_mtime = mtime
                    print(f"[LIVE] ROI reloaded ({self.source_key}): ({self.roi.x1},{self.roi.y1})-({self.roi.x2},{self.roi.y2})")
            elif self.roi is None:
                self.roi = load_roi_for_frame(frame_w, frame_h)
        except Exception as e:
            print(f"[LIVE] ROI reload error ({self.source_key}): {e}")

    def _log_db(self, out: dict, warning_device_on: bool):
        now = time.time()
        should_log = False

        if (out["child_in_roi"] != self.last_logged["child_in_roi"] or
            warning_device_on != self.last_logged["warning_device_on"]):
            should_log = True

        if (now - self.last_logged["last_log_time"]) >= self.LOG_HEARTBEAT_SEC:
            should_log = True

        if not should_log:
            return

        db_payload = {
            "timestamp_iso": out["timestamp_iso"],
            "source": "yolo",
            "child_in_roi": out["child_in_roi"],
            "roi_status": out["roi_status"],
            "confidence": out["confidence"],
            "latency_ms": out["latency_ms"],
            "warning_logic_on": out["child_in_roi"],
            "switch_enabled": True,
            "warning_device_on": warning_device_on,
            "battery_percent": 0.0,
            "solar_status": "N/A",
            "scenario": "Live",
            "camera_status": "OK",
            "edge_status": "OK",
            "led_driver_status": "Ready",
        }
        insert_event(db_payload)

        self.last_logged["child_in_roi"] = out["child_in_roi"]
        self.last_logged["warning_device_on"] = warning_device_on
        self.last_logged["last_log_time"] = now

    def _log_perf(self, last_latency_ms: int):
        now = time.time()
        if (now - self.last_perf_ts) < 5.0:
            return
        window = max(0.001, now - self.last_perf_ts)
        capture_fps = (self.capture_frames - self.last_perf_capture) / window
        infer_fps = (self.infer_frames - self.last_perf_infer) / window
        self.last_perf_ts = now
        self.last_perf_capture = self.capture_frames
        self.last_perf_infer = self.infer_frames
        print(
            f"[LIVE][PERF] source={self.source_key} viewers={self.viewer_count} "
            f"capture_fps={capture_fps:.1f} infer_fps={infer_fps:.1f} latency_ms={last_latency_ms}"
        )

    def _inference_loop(self):
        next_run = time.perf_counter()
        while not self.stop_event.is_set():
            now_perf = time.perf_counter()
            wait_s = next_run - now_perf
            if wait_s > 0:
                time.sleep(min(wait_s, 0.02))
                continue

            next_run = max(next_run + INFER_INTERVAL_SEC, time.perf_counter())

            with self.state_lock:
                raw = self.latest_frame_raw
            if raw is None:
                continue

            frame = raw.copy()
            h, w = frame.shape[:2]
            self._refresh_roi(w, h)
            roi = self.roi or ROI(0, 0, w - 1, h - 1)

            out_raw = self.detector.infer_frame(frame, roi)
            child_in_roi_stable, confidence_stable = self.stabilizer.update(
                out_raw.get("child_in_roi_raw", False),
                out_raw.get("confidence_raw", 0.0),
            )
            out = {
                "timestamp_iso": out_raw["timestamp_iso"],
                "latency_ms": out_raw["latency_ms"],
                "confidence": confidence_stable,
                "child_in_roi": bool(child_in_roi_stable),
                "roi_status": "CHILD_IN_ROI" if child_in_roi_stable else "CLEAR",
                "confidence_raw": out_raw.get("confidence_raw", 0.0),
                "child_in_roi_raw": bool(out_raw.get("child_in_roi_raw", False)),
                "detections": out_raw.get("detections", []),
            }
            warning_device_on = bool(self.warn_ctrl.update(out["child_in_roi"]))

            payload = {
                "timestamp_iso": out["timestamp_iso"],
                "latency_ms": out["latency_ms"],
                "confidence": out["confidence"],
                "child_in_roi": out["child_in_roi"],
                "confidence_raw": out["confidence_raw"],
                "child_in_roi_raw": out["child_in_roi_raw"],
                "roi_status": out["roi_status"],
                "warning_device_on": warning_device_on,
                "source": "yolo",
            }
            socketio.emit("status_update", payload)

            try:
                self._log_db(out, warning_device_on)
            except Exception as e:
                print(f"[LIVE] DB logging error ({self.source_key}): {e}")

            annotated = _draw_overlay(
                frame.copy(),
                roi,
                out.get("detections", []),
                out["child_in_roi"],
            )
            with self.state_lock:
                self.latest_frame_annotated = annotated

            self.infer_frames += 1
            self._log_perf(last_latency_ms=out["latency_ms"])


class LiveSessionManager:
    def __init__(self):
        self._lock = threading.Lock()
        self._sessions: Dict[str, LiveSession] = {}

    def acquire(self, source_str: str) -> LiveSession:
        source_key, source_kind, source_value = _resolve_video_source(source_str)
        with self._lock:
            session = self._sessions.get(source_key)
            if session is None:
                session = LiveSession(source_key, source_kind, source_value)
                session.start()
                self._sessions[source_key] = session
            session.viewer_count += 1
            viewers = session.viewer_count
        print(f"[LIVE] Viewer joined | source={source_key} | viewers={viewers}")
        return session

    def release(self, source_key: str):
        session_to_stop = None
        with self._lock:
            session = self._sessions.get(source_key)
            if session is None:
                return
            session.viewer_count = max(0, session.viewer_count - 1)
            viewers = session.viewer_count
            if viewers == 0:
                session_to_stop = self._sessions.pop(source_key)
        print(f"[LIVE] Viewer left | source={source_key} | viewers={viewers}")
        if session_to_stop is not None:
            session_to_stop.stop()


live_sessions = LiveSessionManager()


# --------------------------------------------------------------------------------
# API Routes
# --------------------------------------------------------------------------------

@app.route("/video_feed")
def video_feed_route():
    overlay = request.args.get("overlay", "1") == "1"
    source_uri = request.args.get("source", "")
    try:
        session = live_sessions.acquire(source_uri)
    except Exception as e:
        print(f"[LIVE] Cannot start session: {e}")
        return Response(status=503)
    return Response(gen_frames(session, overlay=overlay), mimetype="multipart/x-mixed-replace; boundary=frame")


def gen_frames(session: LiveSession, overlay: bool = True):
    frame_interval = 1.0 / STREAM_FPS
    last_perf_log = time.time()
    stream_count = 0
    try:
        while not session.stop_event.is_set():
            t0 = time.perf_counter()

            frame = session.get_stream_frame(overlay=overlay)
            if frame is None:
                time.sleep(0.01)
                continue

            ret, buffer = cv2.imencode(".jpg", frame)
            if ret:
                stream_count += 1
                frame_bytes = buffer.tobytes()
                yield (b"--frame\r\n"
                       b"Content-Type: image/jpeg\r\n\r\n" + frame_bytes + b"\r\n")

            now = time.time()
            if (now - last_perf_log) >= 5.0:
                stream_fps = stream_count / max(0.001, now - last_perf_log)
                print(f"[LIVE][PERF] source={session.source_key} stream_fps={stream_fps:.1f} overlay={int(overlay)}")
                stream_count = 0
                last_perf_log = now

            elapsed = time.perf_counter() - t0
            sleep_for = frame_interval - elapsed
            if sleep_for > 0:
                time.sleep(sleep_for)
    finally:
        live_sessions.release(session.source_key)


def _probe_local_cameras(max_index: int = 8):
    cameras = []
    max_index = max(1, min(int(max_index), 16))

    for idx in range(max_index):
        cap = cv2.VideoCapture(idx)
        opened = cap.isOpened()
        if not opened:
            cap.release()
            continue

        cap.set(cv2.CAP_PROP_FRAME_WIDTH, CAM_WIDTH)
        cap.set(cv2.CAP_PROP_FRAME_HEIGHT, CAM_HEIGHT)
        ok, frame = cap.read()

        width = 0
        height = 0
        if ok and frame is not None:
            height, width = frame.shape[:2]
        else:
            width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH) or 0)
            height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT) or 0)

        cap.release()
        cameras.append({
            "index": idx,
            "ok": bool(ok),
            "width": int(width),
            "height": int(height),
        })

    return cameras


@app.get("/api/cameras/probe")
def api_cameras_probe():
    """
    Probe local camera indices so frontend device selection matches OpenCV index mapping.
    """
    try:
        max_arg = int(request.args.get("max", 8))
    except (TypeError, ValueError):
        max_arg = 8

    cameras = _probe_local_cameras(max_index=max_arg)
    return jsonify({
        "ok": True,
        "max_checked": max(1, min(int(max_arg), 16)),
        "count": len(cameras),
        "cameras": cameras,
        "timestamp_iso": datetime.now(timezone.utc).isoformat(),
    })


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
    Always computes from ALL matching rows in the DB - never limited by page size.
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

    # Run the Flask-SocketIO server.
    socketio.run(app, host="0.0.0.0", port=5000, debug=True, allow_unsafe_werkzeug=True)
