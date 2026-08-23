import os
import threading
import time
import functools
from datetime import datetime, timezone, timedelta, time as dt_time
from typing import Optional, Union

from dotenv import load_dotenv
from flask import Flask, render_template, request, jsonify, Response, session, redirect, url_for
from flask_socketio import SocketIO, join_room

import cv2
import json
from pathlib import Path
from cv_inference import ChildLikeDetector, ROI
from warning_controller import TemporalVoteStabilizer, WarningController
from detection_tracker import DetectionTracker
from hardware_controller import ESP32Relay

load_dotenv()\

PROJECT_ROOT = Path(__file__).resolve().parent
DEFAULT_MODEL_PATH = PROJECT_ROOT / "models" / "manual_crosswalk_detector.pt"
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


def _resolve_model_path() -> Path:
    raw = (os.getenv("MODEL_PATH") or "").strip()
    if not raw:
        return DEFAULT_MODEL_PATH

    path = Path(raw).expanduser()
    if not path.is_absolute():
        path = PROJECT_ROOT / path
    return path


# ────────────────────────────────────────────────────────────────────────────
# Time-Based Scenario Recognition
# ────────────────────────────────────────────────────────────────────────────
# Automatically labels detection events based on the current Manila local
# time (UTC+8).  Replaces static "Live" / "Video Test" labels so TMC
# Officers can identify high-risk school windows in the Scenario chart.
# ────────────────────────────────────────────────────────────────────────────
def get_time_scenario() -> str:
    """Return a scenario label based on the current Manila local time."""
    manila_now = datetime.now(timezone.utc) + timedelta(hours=8)
    t = manila_now.time()

    if dt_time(6, 0) <= t < dt_time(8, 30):
        return "Morning School Entry"
    if dt_time(11, 0) <= t < dt_time(13, 30):
        return "Mid-Day Shift"
    if dt_time(15, 30) <= t < dt_time(17, 0):
        return "Afternoon Dismissal"
    return "Standard Daylight Ops"


CHILD_CONF = _env_float("LIVE_CHILD_CONF", 0.65)
MIN_CHILD_BBOX_RATIO = _env_float("LIVE_MIN_CHILD_BBOX_RATIO", 0.18)
DOMINANCE_IOU = _env_float("LIVE_DOMINANCE_IOU", 0.70)
WARNING_HOLD_SECONDS = _env_float("LIVE_WARNING_HOLD_SECONDS", 2.0)
WARNING_MIN_TOGGLE_SEC = _env_float("LIVE_WARNING_MIN_TOGGLE_SEC", 0.75)
YOLO_IMGSZ = _env_int("LIVE_YOLO_IMGSZ", 640)
INFER_INTERVAL_SEC = _env_float("LIVE_INFER_INTERVAL_SEC", 0.125)
STREAM_FPS = max(1.0, _env_float("LIVE_STREAM_FPS", 25.0))
STREAM_SCALE = max(0.1, min(1.0, _env_float("LIVE_STREAM_SCALE", 0.5)))  # downscale for MJPEG only
CAM_WIDTH = _env_int("LIVE_CAM_WIDTH", 640)
CAM_HEIGHT = _env_int("LIVE_CAM_HEIGHT", 360)

# Anti-Flicker Tracker Settings
TRACKER_IOU_THRESHOLD = _env_float("TRACKER_IOU_THRESHOLD", 0.25)
TRACKER_MAX_MISSES = _env_int("TRACKER_MAX_MISSES", 25)
TRACKER_SMOOTH_ALPHA = _env_float("TRACKER_SMOOTH_ALPHA", 0.6)
TRACKER_CONF_SMOOTH_ALPHA = _env_float("TRACKER_CONF_SMOOTH_ALPHA", 0.4)
CLASS_SWITCH_FRAMES = _env_int("CLASS_SWITCH_FRAMES", 15)  # consecutive opposing frames to switch label

# Feet-zone detection — only the bottom portion of the child bbox is checked against ROI
FEET_HEIGHT_RATIO = _env_float("FEET_HEIGHT_RATIO", 0.15)


MODEL_PATH = _resolve_model_path()

# Video Testing Mode
TEST_VIDEO_FPS = _env_float("TEST_VIDEO_FPS", 0)
TEST_VIDEO_MAX_UPLOAD_MB = _env_int("TEST_VIDEO_MAX_UPLOAD_MB", 500)
TEST_VIDEOS_DIR = PROJECT_ROOT / "test_videos"
TEST_VIDEOS_DIR.mkdir(exist_ok=True)

# Hikvision CCTV — single fixed camera source (auto-connect on boot)
HIKVISION_RTSP_URL = (os.getenv("HIKVISION_RTSP_URL") or "").strip()
HIKVISION_RECONNECT_SEC = _env_float("HIKVISION_RECONNECT_SEC", 5.0)

# ESP32 Warning Relay
ESP32_ENABLED = os.getenv("ESP32_ENABLED", "false").strip().lower() in ("true", "1", "yes")
ESP32_PORT = (os.getenv("ESP32_PORT") or "COM5").strip()
ESP32_BAUD = _env_int("ESP32_BAUD", 115200)

# FFMPEG low-latency flags for RTSP capture (must be set before VideoCapture)
# - rtsp_transport=tcp: reliable delivery (same as Hikvision's own viewer)
# - fflags=nobuffer: don't buffer input packets
# - flags=low_delay: minimize decode latency
# - analyzeduration/probesize: start decoding faster
os.environ["OPENCV_FFMPEG_CAPTURE_OPTIONS"] = (
    "rtsp_transport;tcp|fflags;nobuffer|flags;low_delay|analyzeduration;100000|probesize;100000"
)


# DB Imports
import csv
import io
from db import (
    init_db, insert_event, fetch_events, stream_events, RAW_EXPORT_FIELDS,
    fetch_analytics_aggregates, authenticate_user, get_user_by_username, update_user_password
)

app = Flask(__name__)
app.config["SECRET_KEY"] = os.getenv("SECRET_KEY", "dev-secret-key-change-in-production")
# cors_allowed_origins="*" allows the frontend to connect from different ports
# This is crucial for local dev where frontend might be served differently (though here it's same origin)
socketio = SocketIO(app, cors_allowed_origins="*", async_mode="threading")

# ESP32 Hardware Relay (lazy init — connects on first detection, not at import)
esp32_relay = ESP32Relay(
    port=ESP32_PORT,
    baud=ESP32_BAUD,
    enabled=ESP32_ENABLED,
)

# --------------------------------------------------------------------------------
# Authentication & RBAC
# --------------------------------------------------------------------------------

def login_required(f):
    """Decorator to protect routes that require authentication (any role)."""
    @functools.wraps(f)
    def decorated_function(*args, **kwargs):
        if not session.get("logged_in"):
            if request.path.startswith("/api/"):
                return jsonify({"ok": False, "error": "unauthorized"}), 401
            return redirect(url_for("landing"))
        return f(*args, **kwargs)
    return decorated_function

def role_required(*allowed_roles):
    """Decorator to enforce role-based access control.
    Usage: @role_required('tmc_officer') or @role_required('tmc_officer', 'it_specialist')
    """
    def decorator(f):
        @functools.wraps(f)
        def decorated_function(*args, **kwargs):
            if not session.get("logged_in"):
                if request.path.startswith("/api/"):
                    return jsonify({"ok": False, "error": "unauthorized"}), 401
                return redirect(url_for("landing"))
            user_role = session.get("role")
            if allowed_roles and user_role not in allowed_roles:
                if request.path.startswith("/api/"):
                    return jsonify({
                        "ok": False,
                        "error": "forbidden",
                        "message": f"Requires one of roles: {', '.join(allowed_roles)}"
                    }), 403
                return render_template("403.html", user_role=user_role), 403
            return f(*args, **kwargs)
        return decorated_function
    return decorator

# --------------------------------------------------------------------------------
# Helper Functions
# --------------------------------------------------------------------------------

def load_roi_for_frame(frame_w: int, frame_h: int) -> ROI:
    """
    Loads ROI saved from Settings ROI tool and scales to current frame size.
    Supports both polygon format (4 corner points) and legacy rect format.
    """
    if not ROI_PATH.exists():
        return ROI.from_rect(0, 0, frame_w - 1, frame_h - 1, frame_w, frame_h)

    data = json.loads(ROI_PATH.read_text(encoding="utf-8"))
    base_w = int(data.get("image_w", frame_w))
    base_h = int(data.get("image_h", frame_h))
    sx = frame_w / base_w
    sy = frame_h / base_h

    if "polygon" in data:
        pts = data["polygon"]
        import numpy as _np
        polygon = _np.array([[int(p["x"] * sx), int(p["y"] * sy)] for p in pts], dtype=_np.int32)
        return ROI(polygon, frame_w, frame_h)
    else:
        x1 = int(int(data.get("x1", 0)) * sx)
        y1 = int(int(data.get("y1", 0)) * sy)
        x2 = int(int(data.get("x2", 0)) * sx)
        y2 = int(int(data.get("y2", 0)) * sy)
        return ROI.from_rect(x1, y1, x2, y2, frame_w, frame_h)

# --------------------------------------------------------------------------------
# Routes & Events
# --------------------------------------------------------------------------------

@app.route("/")
def landing():
    """Landing / Welcome page with login form."""
    if session.get("logged_in"):
        return redirect(url_for("dashboard"))
    return render_template("landing.html")

@app.route("/dashboard")
@login_required
def dashboard():
    """Dynamic router — redirects to the role-appropriate dashboard."""
    role = session.get("role")
    if role == "it_specialist":
        return redirect(url_for("dashboard_it"))
    return redirect(url_for("dashboard_tmc"))

@app.route("/dashboard/tmc")
@role_required("tmc_officer")
def dashboard_tmc():
    """TMC Officer dashboard — live view, ROI, logs, analytics, reports."""
    return render_template("tmc_dashboard.html",
                           username=session.get("username"),
                           role=session.get("role"),
                           full_name=session.get("full_name", "TMC Officer"))

@app.route("/dashboard/it")
@role_required("it_specialist")
def dashboard_it():
    """IT Specialist dashboard — system status, video sim, data export, model accuracy."""
    return render_template("it_dashboard.html",
                           username=session.get("username"),
                           role=session.get("role"),
                           full_name=session.get("full_name", "IT Specialist"))

@app.route("/api/login", methods=["POST"])
def api_login():
    """Authenticate credentials against MySQL users table."""
    data = request.get_json(silent=True) or {}
    username = (data.get("username") or "").strip()
    password = (data.get("password") or "").strip()

    user = authenticate_user(username, password)
    if user:
        session["logged_in"] = True
        session["username"] = user["username"]
        session["role"] = user["role"]
        session["full_name"] = user["full_name"]
        session["user_id"] = user["id"]
        session.permanent = True
        return jsonify({"ok": True, "role": user["role"], "redirect": url_for("dashboard")})

    return jsonify({"ok": False, "error": "Invalid username or password."}), 401

@app.route("/api/logout")
def api_logout():
    """Clear the session and redirect to the landing page."""
    session.clear()
    return redirect(url_for("landing"))

@app.route("/api/user/change-password", methods=["POST"])
@login_required
def api_change_password():
    """Allow authenticated users to update their own password."""
    data = request.get_json(silent=True) or {}
    current_password = (data.get("current_password") or "").strip()
    new_password = (data.get("new_password") or "").strip()

    if not current_password or not new_password:
        return jsonify({"ok": False, "error": "Both current and new password are required."}), 400

    if len(new_password) < 6:
        return jsonify({"ok": False, "error": "New password must be at least 6 characters."}), 400

    # Verify current password matches
    username = session.get("username")
    user = authenticate_user(username, current_password)
    if not user:
        return jsonify({"ok": False, "error": "Current password is incorrect."}), 401

    # Update to new password
    if update_user_password(username, new_password):
        return jsonify({"ok": True, "message": "Password updated successfully."})
    return jsonify({"ok": False, "error": "Failed to update password. Please try again."}), 500

@app.get("/api/roi")
@login_required
def api_get_roi():
    if not ROI_PATH.exists():
        return jsonify({"ok": False, "error": "roi_not_set"}), 404
    data = json.loads(ROI_PATH.read_text(encoding="utf-8"))
    return jsonify({"ok": True, "roi": data})

def _validate_roi_payload(d: dict):
    """Validate polygon or legacy rect ROI payload."""
    if "polygon" in d:
        pts = d.get("polygon", [])
        if not isinstance(pts, list) or len(pts) < 3 or len(pts) > 8:
            return False, "polygon_invalid", d
        try:
            iw = int(d["image_w"])
            ih = int(d["image_h"])
        except (KeyError, TypeError, ValueError):
            return False, "missing_image_size", d
        if iw <= 0 or ih <= 0:
            return False, "bad_image_size", d
        clean_pts = []
        for p in pts:
            try:
                px = max(0, min(int(round(p["x"])), iw))
                py = max(0, min(int(round(p["y"])), ih))
                clean_pts.append({"x": px, "y": py})
            except (KeyError, TypeError, ValueError):
                return False, "bad_point", d
        clean = {"polygon": clean_pts, "image_w": iw, "image_h": ih}
        return True, "", clean
    else:
        required = ["x1", "y1", "x2", "y2", "image_w", "image_h"]
        for k in required:
            if k not in d:
                return False, f"missing:{k}", d
        try:
            iw, ih = int(d["image_w"]), int(d["image_h"])
        except Exception:
            return False, "type_error", d
        if iw <= 0 or ih <= 0:
            return False, "bad_image_size", d
        x1 = max(0, min(int(round(d["x1"])), iw - 1))
        y1 = max(0, min(int(round(d["y1"])), ih - 1))
        x2 = max(x1 + 1, min(int(round(d["x2"])), iw))
        y2 = max(y1 + 1, min(int(round(d["y2"])), ih))
        clean = {"x1": x1, "y1": y1, "x2": x2, "y2": y2, "image_w": iw, "image_h": ih}
        return True, "", clean

@app.post("/api/roi")
@role_required("tmc_officer")
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
    Joins the client into a role-specific Socket.IO room and sends
    the current session state and telemetry.
    """
    from flask import request as _req  # Socket.IO connect has access to Flask session
    role = session.get("role", "unknown")
    join_room(f"role_{role}")
    print(f"Client connected (role={role}, sid={_req.sid})")

    if active_session is not None:
        cam_status = "OK" if active_session.camera_online else "OFFLINE"
        socketio.emit("status_update", _build_idle_payload(camera_status=cam_status), room=_req.sid)
        socketio.emit("camera_status", active_session.get_status(), room=_req.sid)
        socketio.emit("mode_update", {
            "mode": current_mode,
            "video_filename": getattr(active_session, '_video_filename', None)
        }, room=_req.sid)
    else:
        socketio.emit("status_update", _build_idle_payload(camera_status="OFFLINE"), room=_req.sid)
        socketio.emit("mode_update", {"mode": current_mode}, room=_req.sid)

# --------------------------------------------------------------------------------
# Live Pipeline
# --------------------------------------------------------------------------------

# (Multi-source camera helpers removed — Hikvision is the sole source)


_last_cpu_sample_ts = 0.0
_cached_cpu_pct = 0.0
_cached_ram_pct = 0.0

def get_edge_compute_metrics() -> dict:
    """Sample CPU % and RAM % using psutil with 1-second cached throttling."""
    global _last_cpu_sample_ts, _cached_cpu_pct, _cached_ram_pct
    now = time.time()
    if (now - _last_cpu_sample_ts) >= 1.0:
        try:
            import psutil
            _cached_cpu_pct = round(psutil.cpu_percent(interval=None), 1)
            _cached_ram_pct = round(psutil.virtual_memory().percent, 1)
            _last_cpu_sample_ts = now
        except Exception:
            pass
    return {
        "cpu_percent": _cached_cpu_pct,
        "ram_percent": _cached_ram_pct,
    }


def _build_idle_payload(camera_status: str, edge_status: str = "OK") -> dict:
    relay_diag = esp32_relay.get_diagnostics() if "esp32_relay" in globals() else {
        "connected": False, "label": "Disconnected", "heartbeat_ok": False, "heartbeat_label": "Not Responding", "port": "COM5"
    }
    edge_metrics = get_edge_compute_metrics()
    return {
        "timestamp_iso": datetime.now(timezone.utc).isoformat(),
        "child_in_roi": False,
        "child_in_roi_raw": False,
        "roi_status": "CLEAR",
        "confidence": 0.0,
        "confidence_raw": 0.0,
        "latency_ms": 0,
        "stream_latency_ms": 0,
        "fps": 0.0,
        "capture_fps": 0.0,
        "infer_fps": 0.0,
        "frame_drop_rate": 0.0,
        "edge_compute": edge_metrics,
        "relay_status": {
            "connected": relay_diag["connected"],
            "label": relay_diag["label"],
            "port": relay_diag["port"],
            "heartbeat_ok": relay_diag["heartbeat_ok"],
            "heartbeat_label": relay_diag["heartbeat_label"],
        },
        "warning_device_on": False,
        "source": "idle",
        "camera_status": camera_status,
        "edge_status": edge_status,
    }


def _draw_overlay(frame, roi: ROI, detections, child_in_roi: bool, status_note: Optional[str] = None):
    if roi:
        roi_overlay = frame.copy()
        if child_in_roi:
            fill_color = (0, 0, 200)   # Red tint = WARNING
            border_color = (0, 0, 255)
        else:
            fill_color = (0, 180, 0)   # Green tint = CLEAR
            border_color = (0, 255, 0)
        # Draw filled polygon overlay
        pts = roi.polygon.reshape((-1, 1, 2))
        cv2.fillPoly(roi_overlay, [roi.polygon], fill_color)
        cv2.addWeighted(roi_overlay, 0.08, frame, 0.92, 0, frame)
        cv2.polylines(frame, [pts], isClosed=True, color=border_color, thickness=2)

        roi_label = "ROI: CHILD DETECTED" if child_in_roi else "ROI: CLEAR"
        (tw, th), _ = cv2.getTextSize(roi_label, cv2.FONT_HERSHEY_SIMPLEX, 0.8, 2)
        lx = roi.x1
        ly = max(th + 10, roi.y1 - 10)
        cv2.rectangle(frame, (lx, ly - th - 6), (lx + tw + 8, ly + 4), (0, 0, 0), -1)
        cv2.putText(frame, roi_label, (lx + 4, ly), cv2.FONT_HERSHEY_SIMPLEX, 0.8, border_color, 2, cv2.LINE_AA)

    if status_note:
        (tw, th), _ = cv2.getTextSize(status_note, cv2.FONT_HERSHEY_SIMPLEX, 0.7, 2)
        pad = 10
        top = 16
        cv2.rectangle(frame, (pad, top), (pad + tw + 16, top + th + 16), (0, 120, 255), -1)
        cv2.putText(
            frame,
            status_note,
            (pad + 8, top + th + 4),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.7,
            (255, 255, 255),
            2,
            cv2.LINE_AA,
        )

    for d in detections:
        x1, y1, x2, y2 = d["bbox"]
        conf = d["conf"]
        cls = d["cls"]
        if cls == 1:
            color = (0, 255, 255)  # Cyan
            label = f"child {conf:.2f}"
            thickness = 1
        else:
            color = (255, 180, 50)  # Orange
            label = f"adult {conf:.2f}"
            thickness = 1
        cv2.rectangle(frame, (x1, y1), (x2, y2), color, thickness)
        (tw, th), _ = cv2.getTextSize(label, cv2.FONT_HERSHEY_SIMPLEX, 0.7, 2)
        cv2.rectangle(frame, (x1, max(0, y1 - th - 8)), (x1 + tw + 6, y1), (0, 0, 0), -1)
        cv2.putText(frame, label, (x1 + 3, max(th + 3, y1 - 3)), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 255, 255), 2, cv2.LINE_AA)

    return frame


class LiveSession:
    LOG_HEARTBEAT_SEC = 10.0

    def __init__(self, rtsp_url: str, reconnect_sec: float = 5.0):
        self.rtsp_url = rtsp_url
        self.reconnect_sec = reconnect_sec
        self.source_key = "hikvision"

        # Camera / stream state
        self.camera_online = False
        self.stream_connected = False
        self.reconnect_attempts = 0
        self.last_frame_time: float = 0.0

        self.detector: Optional[ChildLikeDetector] = None
        self.detector_error: Optional[str] = None
        self._load_detector()
        self.tracker = DetectionTracker(
            iou_threshold=TRACKER_IOU_THRESHOLD,
            max_misses=TRACKER_MAX_MISSES,
            smooth_alpha=TRACKER_SMOOTH_ALPHA,
            conf_smooth_alpha=TRACKER_CONF_SMOOTH_ALPHA,
            class_switch_frames=CLASS_SWITCH_FRAMES,
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
        self.viewer_count = 0
        self.capture_fps = 0.0
        self.infer_fps = 0.0
        self.stream_latency_ms = 0
        self.latest_frame_capture_perf = 0.0
        self.last_perf_ts = time.time()
        self.last_perf_capture = 0
        self.last_perf_infer = 0
        self.last_relay_hb_ts = 0.0

    def _load_detector(self):
        if not MODEL_PATH.exists():
            self.detector = None
            self.detector_error = f"manual model not found at {MODEL_PATH}"
            print(f"[LIVE] Detector unavailable | {self.detector_error}")
            return

        try:
            self.detector = ChildLikeDetector(
                str(MODEL_PATH),
                conf_child=CHILD_CONF,
                min_child_bbox_ratio=MIN_CHILD_BBOX_RATIO,
                dominance_iou=DOMINANCE_IOU,
                imgsz=YOLO_IMGSZ,
                feet_height_ratio=FEET_HEIGHT_RATIO,
            )
            self.detector_error = None
        except Exception as exc:
            self.detector = None
            self.detector_error = f"{type(exc).__name__}: {exc}"
            print(f"[LIVE] Detector load failed | {self.detector_error}")

    def get_status(self) -> dict:
        """Return a snapshot of camera/AI status and system telemetry for the dashboard."""
        relay_diag = esp32_relay.get_diagnostics() if "esp32_relay" in globals() else {
            "connected": False, "label": "Disconnected", "heartbeat_ok": False, "heartbeat_label": "Not Responding", "port": "COM5"
        }
        edge_metrics = get_edge_compute_metrics()
        total_cap = max(1, self.capture_frames)
        dropped = max(0, total_cap - self.infer_frames)
        drop_rate = round((dropped / total_cap) * 100, 1)

        return {
            "camera_online": self.camera_online,
            "stream_connected": self.stream_connected,
            "ai_running": self.detector is not None,
            "ai_error": self.detector_error,
            "reconnect_attempts": self.reconnect_attempts,
            "last_frame_time": self.last_frame_time,
            "rtsp_url_masked": self._mask_url(self.rtsp_url),
            "fps": self.capture_fps,
            "capture_fps": self.capture_fps,
            "infer_fps": self.infer_fps,
            "stream_latency_ms": self.stream_latency_ms,
            "frame_drop_rate": drop_rate,
            "edge_compute": edge_metrics,
            "relay_status": {
                "connected": relay_diag["connected"],
                "label": relay_diag["label"],
                "port": relay_diag["port"],
                "heartbeat_ok": relay_diag["heartbeat_ok"],
                "heartbeat_label": relay_diag["heartbeat_label"],
            },
        }

    @staticmethod
    def _mask_url(url: str) -> str:
        """Hide password in RTSP URL for display."""
        if "@" in url:
            prefix, rest = url.split("@", 1)
            scheme_end = prefix.find("://")
            if scheme_end >= 0:
                return prefix[:scheme_end + 3] + "***:***@" + rest
        return url

    def start(self):
        self.capture_thread = threading.Thread(
            target=self._capture_loop, name="capture-hikvision", daemon=True
        )
        self.inference_thread = threading.Thread(
            target=self._inference_loop, name="infer-hikvision", daemon=True
        )
        self.capture_thread.start()
        self.inference_thread.start()

        detector_state = "ready" if self.detector is not None else f"pending ({self.detector_error})"
        print(
            f"[LIVE] Hikvision session started | url={self._mask_url(self.rtsp_url)} "
            f"| conf_child={CHILD_CONF:.2f} | imgsz={YOLO_IMGSZ} "
            f"| min_bbox_ratio={MIN_CHILD_BBOX_RATIO:.2f} "
            f"| stream_fps={STREAM_FPS:.1f} | infer_interval={INFER_INTERVAL_SEC:.3f}s "
            f"| detector={detector_state}"
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
        self.camera_online = False
        self.stream_connected = False
        print(f"[LIVE] Hikvision session stopped")

    def get_stream_frame(self, overlay: bool):
        with self.state_lock:
            if overlay and self.latest_frame_annotated is not None:
                return self.latest_frame_annotated
            return self.latest_frame_raw

    def _open_capture(self) -> cv2.VideoCapture:
        # Use FFMPEG backend with low-latency RTSP flags
        cap = cv2.VideoCapture(self.rtsp_url, cv2.CAP_FFMPEG)
        # Low-latency: minimize RTSP buffering
        cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
        # Set resolution to match .env
        if CAM_WIDTH > 0:
            cap.set(cv2.CAP_PROP_FRAME_WIDTH, CAM_WIDTH)
        if CAM_HEIGHT > 0:
            cap.set(cv2.CAP_PROP_FRAME_HEIGHT, CAM_HEIGHT)
        return cap


    def _capture_loop(self):
        """Auto-connect and auto-reconnect loop for Hikvision RTSP stream."""
        while not self.stop_event.is_set():
            # --- Connect / Reconnect ---
            if self.cap is None or not self.cap.isOpened():
                self.camera_online = False
                self.stream_connected = False
                self.reconnect_attempts += 1
                _emit_camera_status(self)
                print(
                    f"[LIVE] Connecting to Hikvision... "
                    f"(attempt {self.reconnect_attempts})"
                )
                try:
                    if self.cap is not None:
                        self.cap.release()
                    self.cap = self._open_capture()
                    if self.cap.isOpened():
                        self.camera_online = True
                        self.stream_connected = True
                        self.reconnect_attempts = 0
                        _emit_camera_status(self)
                        print("[LIVE] Hikvision stream connected")
                    else:
                        print(
                            f"[LIVE] Hikvision stream failed — "
                            f"retrying in {self.reconnect_sec}s"
                        )
                        self.cap.release()
                        self.cap = None
                        self.stop_event.wait(self.reconnect_sec)
                        continue
                except Exception as exc:
                    print(f"[LIVE] Hikvision connect error: {exc}")
                    if self.cap is not None:
                        try:
                            self.cap.release()
                        except Exception:
                            pass
                    self.cap = None
                    self.stop_event.wait(self.reconnect_sec)
                    continue

            # --- Read frames (drain buffer to get the LATEST frame) ---
            # FFMPEG buffers 2-5 frames internally even with nobuffer.
            # grab() discards old frames quickly, then retrieve() decodes only the latest.
            ok = True
            for _ in range(4):  # drain up to 4 stale buffered frames
                ok = self.cap.grab()
                if not ok:
                    break
            if ok:
                ok, frame = self.cap.retrieve()
            else:
                frame = None

            if not ok or frame is None:
                print("[LIVE] Hikvision frame read failed — will reconnect")
                self.cap.release()
                self.cap = None
                self.camera_online = False
                self.stream_connected = False
                _emit_camera_status(self)
                self.stop_event.wait(self.reconnect_sec)
                continue

            now_perf = time.perf_counter()
            with self.state_lock:
                self.latest_frame_raw = frame
                self.latest_frame_capture_perf = now_perf
            self.last_frame_time = time.time()
            self.capture_frames += 1

            # Rolling FPS calculation (updated every 1s)
            now = time.time()
            dt = now - self.last_perf_ts
            if dt >= 1.0:
                self.capture_fps = round((self.capture_frames - self.last_perf_capture) / max(0.001, dt), 1)
                self.infer_fps = round((self.infer_frames - self.last_perf_infer) / max(0.001, dt), 1)
                self.last_perf_ts = now
                self.last_perf_capture = self.capture_frames
                self.last_perf_infer = self.infer_frames


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
            "child_count": out.get("child_count", 0),
            "battery_percent": 0.0,
            "solar_status": "N/A",
            "scenario": get_time_scenario(),
            "camera_status": "OK",
            "edge_status": "OK",
            "led_driver_status": esp32_relay.status,
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
                capture_perf = self.latest_frame_capture_perf
            if raw is None:
                continue

            # Stream transport latency (camera grab to inference entry)
            stream_latency_ms = max(0, int((time.perf_counter() - capture_perf) * 1000)) if capture_perf > 0 else 0
            self.stream_latency_ms = stream_latency_ms

            # Frame drop rate calculation
            total_cap = max(1, self.capture_frames)
            dropped = max(0, total_cap - self.infer_frames)
            frame_drop_rate = round((dropped / total_cap) * 100, 1)

            # Periodic ESP32 heartbeat check (every 3s)
            now = time.time()
            if (now - self.last_relay_hb_ts) >= 3.0:
                self.last_relay_hb_ts = now
                try:
                    esp32_relay.check_heartbeat()
                except Exception:
                    pass

            frame = raw.copy()
            h, w = frame.shape[:2]
            self._refresh_roi(w, h)
            roi = self.roi or ROI(0, 0, w - 1, h - 1)

            if self.detector is None:
                payload = _build_idle_payload(camera_status="OK", edge_status="ERROR")
                socketio.emit("status_update", payload)
                annotated = _draw_overlay(
                    frame.copy(),
                    roi,
                    [],
                    False,
                    status_note="MODEL NOT READY",
                )
                with self.state_lock:
                    self.latest_frame_annotated = annotated
                continue

            out_raw = self.detector.infer_frame(frame, roi)
            
            # --- 1. Apply Anti-Flicker Box Tracking ---
            raw_detections = out_raw.get("detections", [])
            tracked_detections = self.tracker.update(raw_detections)

            # --- 2. Recalculate ROI state based on smoothed/ghost boxes ---
            min_bbox_h = h * MIN_CHILD_BBOX_RATIO
            tracked_child_in_roi_raw = False
            tracked_confidence_raw = 0.0
            child_count_in_roi = 0

            for d in tracked_detections:
                if d["cls"] == 1 and d["conf"] >= CHILD_CONF:
                    x1, y1, x2, y2 = d["bbox"]
                    if (y2 - y1) >= min_bbox_h:
                        if roi.feet_in_roi(float(x1), float(y1), float(x2), float(y2), FEET_HEIGHT_RATIO):
                            tracked_child_in_roi_raw = True
                            tracked_confidence_raw = max(tracked_confidence_raw, d["conf"])
                            child_count_in_roi += 1

            # --- 3. Vote Stabilizer for the global warning status ---
            child_in_roi_stable, confidence_stable = self.stabilizer.update(
                tracked_child_in_roi_raw,
                tracked_confidence_raw,
            )
            
            out = {
                "timestamp_iso": out_raw["timestamp_iso"],
                "latency_ms": out_raw["latency_ms"],
                "confidence": confidence_stable,
                "child_in_roi": bool(child_in_roi_stable),
                "roi_status": "CHILD_IN_ROI" if child_in_roi_stable else "CLEAR",
                "confidence_raw": tracked_confidence_raw,
                "child_in_roi_raw": tracked_child_in_roi_raw,
                "child_count": child_count_in_roi,
                "detections": tracked_detections,
            }
            warning_device_on = bool(self.warn_ctrl.update(out["child_in_roi"]))

            # --- Send command to ESP32 relay ---
            esp32_relay.set_state(warning_device_on)

            relay_diag = esp32_relay.get_diagnostics()
            edge_metrics = get_edge_compute_metrics()

            payload = {
                "timestamp_iso": out["timestamp_iso"],
                "latency_ms": out["latency_ms"],
                "stream_latency_ms": stream_latency_ms,
                "fps": self.capture_fps,
                "capture_fps": self.capture_fps,
                "infer_fps": self.infer_fps,
                "frame_drop_rate": frame_drop_rate,
                "edge_compute": edge_metrics,
                "relay_status": {
                    "connected": relay_diag["connected"],
                    "label": relay_diag["label"],
                    "port": relay_diag["port"],
                    "heartbeat_ok": relay_diag["heartbeat_ok"],
                    "heartbeat_label": relay_diag["heartbeat_label"],
                },
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


# ================================================================================
# VideoTestSession — MP4 file as drop-in replacement for RTSP camera
# ================================================================================

class VideoTestSession(LiveSession):
    """
    Plays a pre-recorded .mp4 file through the same AI pipeline as the live camera.
    Only overrides _capture_loop(); inference, tracking, ROI, warnings, overlay,
    database logging, and MJPEG streaming are all inherited from LiveSession.
    """

    def __init__(self, video_path: str, reconnect_sec: float = 1.0):
        # Initialize base class with a dummy RTSP URL (never used)
        super().__init__(rtsp_url="", reconnect_sec=reconnect_sec)
        self.video_path = str(video_path)
        self.source_key = "video_test"
        self._video_filename = Path(video_path).name

        # Video metadata (populated on first open)
        self._video_fps: float = 0.0
        self._video_total_frames: int = 0
        self._video_duration_sec: float = 0.0
        self._video_current_frame: int = 0

    def get_status(self) -> dict:
        """Override to provide video-specific metadata and system telemetry."""
        relay_diag = esp32_relay.get_diagnostics() if "esp32_relay" in globals() else {
            "connected": False, "label": "Disconnected", "heartbeat_ok": False, "heartbeat_label": "Not Responding", "port": "COM5"
        }
        edge_metrics = get_edge_compute_metrics()
        total_cap = max(1, self.capture_frames)
        dropped = max(0, total_cap - self.infer_frames)
        drop_rate = round((dropped / total_cap) * 100, 1)

        return {
            "camera_online": self.camera_online,
            "stream_connected": self.stream_connected,
            "ai_running": self.detector is not None,
            "ai_error": self.detector_error,
            "reconnect_attempts": 0,
            "last_frame_time": self.last_frame_time,
            "rtsp_url_masked": f"[Video] {self._video_filename}",
            "mode": "video_test",
            "video_filename": self._video_filename,
            "video_fps": self._video_fps,
            "video_total_frames": self._video_total_frames,
            "video_duration_sec": round(self._video_duration_sec, 1),
            "video_current_frame": self._video_current_frame,
            "fps": self.capture_fps or self._video_fps,
            "capture_fps": self.capture_fps or self._video_fps,
            "infer_fps": self.infer_fps,
            "stream_latency_ms": self.stream_latency_ms,
            "frame_drop_rate": drop_rate,
            "edge_compute": edge_metrics,
            "relay_status": {
                "connected": relay_diag["connected"],
                "label": relay_diag["label"],
                "port": relay_diag["port"],
                "heartbeat_ok": relay_diag["heartbeat_ok"],
                "heartbeat_label": relay_diag["heartbeat_label"],
            },
        }

    def _open_capture(self) -> cv2.VideoCapture:
        """Open the MP4 file instead of an RTSP stream."""
        cap = cv2.VideoCapture(self.video_path, cv2.CAP_FFMPEG)
        if cap.isOpened():
            self._video_fps = cap.get(cv2.CAP_PROP_FPS) or 25.0
            self._video_total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
            if self._video_fps > 0 and self._video_total_frames > 0:
                self._video_duration_sec = self._video_total_frames / self._video_fps
        return cap

    def _capture_loop(self):
        """
        Read frames from an MP4 file at its native FPS (or a forced rate).
        Automatically loops the video when it reaches the end for continuous demos.
        """
        target_fps = TEST_VIDEO_FPS if TEST_VIDEO_FPS > 0 else 0  # 0 = use native

        while not self.stop_event.is_set():
            # --- Open / Reopen video ---
            if self.cap is None or not self.cap.isOpened():
                self.camera_online = False
                self.stream_connected = False
                _emit_camera_status(self)
                print(f"[VIDEO_TEST] Opening video: {self._video_filename}")
                try:
                    if self.cap is not None:
                        self.cap.release()
                    self.cap = self._open_capture()
                    if self.cap.isOpened():
                        self.camera_online = True
                        self.stream_connected = True
                        _emit_camera_status(self)
                        actual_fps = target_fps if target_fps > 0 else self._video_fps
                        print(
                            f"[VIDEO_TEST] Video opened: {self._video_filename} "
                            f"| {self._video_total_frames} frames "
                            f"| {self._video_duration_sec:.1f}s "
                            f"| native_fps={self._video_fps:.1f} "
                            f"| playback_fps={actual_fps:.1f}"
                        )
                    else:
                        print(f"[VIDEO_TEST] Failed to open: {self._video_filename}")
                        self.cap = None
                        self.stop_event.wait(2.0)
                        continue
                except Exception as exc:
                    print(f"[VIDEO_TEST] Open error: {exc}")
                    self.cap = None
                    self.stop_event.wait(2.0)
                    continue

            # --- Read frame ---
            ok, frame = self.cap.read()
            if not ok or frame is None:
                # End of video → loop from start
                print(f"[VIDEO_TEST] Video ended — looping: {self._video_filename}")
                self.cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
                self._video_current_frame = 0
                # Reset tracker state on loop to avoid ghost boxes from previous cycle
                self.tracker = DetectionTracker(
                    iou_threshold=TRACKER_IOU_THRESHOLD,
                    max_misses=TRACKER_MAX_MISSES,
                    smooth_alpha=TRACKER_SMOOTH_ALPHA,
                    conf_smooth_alpha=TRACKER_CONF_SMOOTH_ALPHA,
                    class_switch_frames=CLASS_SWITCH_FRAMES,
                )
                continue

            self._video_current_frame = int(self.cap.get(cv2.CAP_PROP_POS_FRAMES))

            now_perf = time.perf_counter()
            with self.state_lock:
                self.latest_frame_raw = frame
                self.latest_frame_capture_perf = now_perf
            self.last_frame_time = time.time()
            self.capture_frames += 1

            # Rolling FPS calculation
            now = time.time()
            dt = now - self.last_perf_ts
            if dt >= 1.0:
                self.capture_fps = round((self.capture_frames - self.last_perf_capture) / max(0.001, dt), 1)
                self.infer_fps = round((self.infer_frames - self.last_perf_infer) / max(0.001, dt), 1)
                self.last_perf_ts = now
                self.last_perf_capture = self.capture_frames
                self.last_perf_infer = self.infer_frames

            # --- Pace to target FPS ---
            playback_fps = target_fps if target_fps > 0 else self._video_fps
            if playback_fps > 0:
                self.stop_event.wait(1.0 / playback_fps)

    def _log_db(self, out: dict, warning_device_on: bool):
        """Override to tag test events with 'Video Test' scenario."""
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
            "child_count": out.get("child_count", 0),
            "battery_percent": 0.0,
            "solar_status": "N/A",
            "scenario": get_time_scenario(),
            "camera_status": "OK",
            "edge_status": "OK",
            "led_driver_status": "Ready",
        }
        insert_event(db_payload)

        self.last_logged["child_in_roi"] = out["child_in_roi"]
        self.last_logged["warning_device_on"] = warning_device_on
        self.last_logged["last_log_time"] = now


# ================================================================================
# Session Management — Active session abstraction for mode switching
# ================================================================================

# The active session can be either a LiveSession (RTSP) or VideoTestSession (MP4)
active_session: Optional[LiveSession] = None
current_mode: str = "live"  # "live" or "video_test"
_session_lock = threading.Lock()


def _emit_camera_status(session: LiveSession):
    """Push camera status to all connected dashboard clients."""
    try:
        socketio.emit("camera_status", session.get_status())
    except Exception:
        pass


# --------------------------------------------------------------------------------
# API Routes
# --------------------------------------------------------------------------------

@app.route("/video_feed")
@login_required
def video_feed_route():
    """MJPEG stream from the active session (live camera or video test)."""
    overlay = request.args.get("overlay", "1") == "1"
    if active_session is None:
        return Response("No active session", status=503)

    return Response(
        gen_frames(active_session, overlay=overlay),
        mimetype="multipart/x-mixed-replace; boundary=frame",
    )


@app.get("/api/camera/snapshot")
@login_required
def api_camera_snapshot():
    """Return a single JPEG frame from the active session (full resolution, no overlay).
    Used by the ROI 'Capture Frame' button."""
    if active_session is None:
        return Response("No active session", status=503)

    frame = active_session.get_stream_frame(overlay=False)
    if frame is None:
        return Response("No frame available", status=503)

    ret, buffer = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 90])
    if not ret:
        return Response("Encoding failed", status=500)

    return Response(
        buffer.tobytes(),
        mimetype="image/jpeg",
        headers={"Cache-Control": "no-cache, no-store"},
    )



def gen_frames(session: LiveSession, overlay: bool = True):
    frame_interval = 1.0 / STREAM_FPS
    last_perf_log = time.time()
    last_frame_sent = time.time()
    last_frame_id = None  # Track frame identity to skip duplicates
    stream_count = 0
    MAX_WAIT_NO_FRAME = 10.0  # seconds — if no frame for this long, close connection

    # JPEG encode params: quality 70 is visually fine at dashboard viewport sizes
    # but encodes 3-4x faster and produces 3-4x smaller files than default (95)
    encode_params = [cv2.IMWRITE_JPEG_QUALITY, 70]

    try:
        while not session.stop_event.is_set():
            t0 = time.perf_counter()

            frame = session.get_stream_frame(overlay=overlay)
            if frame is None:
                # Check if we've waited too long without any frame
                if (time.time() - last_frame_sent) > MAX_WAIT_NO_FRAME:
                    print("[LIVE] gen_frames: no frame for 10s — closing MJPEG connection")
                    return  # Close HTTP connection so browser can detect error + retry
                time.sleep(0.02)
                continue

            # Skip re-encoding if the frame object hasn't changed
            frame_id = id(frame)
            if frame_id == last_frame_id:
                time.sleep(0.01)
                continue
            last_frame_id = frame_id

            last_frame_sent = time.time()

            # Downscale for browser stream (YOLO still gets full-res)
            if STREAM_SCALE < 1.0:
                h, w = frame.shape[:2]
                new_w = int(w * STREAM_SCALE)
                new_h = int(h * STREAM_SCALE)
                frame = cv2.resize(frame, (new_w, new_h), interpolation=cv2.INTER_AREA)

            ret, buffer = cv2.imencode(".jpg", frame, encode_params)
            if ret:
                stream_count += 1
                frame_bytes = buffer.tobytes()
                yield (
                    b"--frame\r\n"
                    b"Content-Type: image/jpeg\r\n\r\n" + frame_bytes + b"\r\n"
                )

            now = time.time()
            if (now - last_perf_log) >= 5.0:
                stream_fps = stream_count / max(0.001, now - last_perf_log)
                print(
                    f"[LIVE][PERF] stream_fps={stream_fps:.1f} overlay={int(overlay)}"
                )
                stream_count = 0
                last_perf_log = now

            elapsed = time.perf_counter() - t0
            sleep_for = frame_interval - elapsed
            if sleep_for > 0:
                time.sleep(sleep_for)
    except GeneratorExit:
        pass


@app.get("/api/camera/status")
@login_required
def api_camera_status():
    """Returns the current active session / AI pipeline status."""
    if active_session is None:
        return jsonify({
            "ok": True,
            "camera_online": False,
            "stream_connected": False,
            "ai_running": False,
            "ai_error": "No active session",
            "reconnect_attempts": 0,
            "last_frame_time": 0,
            "rtsp_url_masked": "",
            "mode": current_mode,
        })
    return jsonify({"ok": True, "mode": current_mode, **active_session.get_status()})


@app.post("/api/camera/reconnect")
@login_required
def api_camera_reconnect():
    """Force the active session to reconnect (only if actually broken)."""
    if active_session is None:
        return jsonify({"ok": False, "error": "No session"}), 503

    # If camera is already online and streaming, don't destroy the connection.
    if active_session.camera_online and active_session.stream_connected:
        print("[LIVE] Reconnect requested but session is already online — skipping")
        return jsonify({"ok": True, "action": "already_online"})

    # Session is genuinely offline/broken — force reconnect
    if active_session.cap is not None:
        try:
            active_session.cap.release()
        except Exception:
            pass
        active_session.cap = None
    active_session.camera_online = False
    active_session.stream_connected = False
    print("[LIVE] Manual reconnect requested — forcing capture reset")
    return jsonify({"ok": True, "action": "reconnecting"})



@app.route("/api/health")
def api_health():
    """
    Simple health check.
    Returns 200 OK if server is running.
    """
    return jsonify({"ok": True})

@app.route("/api/events")
@login_required
def api_events_route():
    """
    Get historical events from DB.
    Returns 503 if DB is unavailable.
    """
    try:
        # Parse Query Params
        range_arg = request.args.get("range", "all")
        start_date = request.args.get("start_date") or request.args.get("start")
        end_date = request.args.get("end_date") or request.args.get("end")
        limit = int(request.args.get("limit", 50))
        offset = int(request.args.get("offset", 0))
        
        # Boolean flags
        warning_only = request.args.get("warning_only", "false").lower() in ("true", "1")
        in_roi_only = request.args.get("in_roi_only", "false").lower() in ("true", "1")
        
        min_conf = float(request.args.get("min_conf", 0.0))
        scenario = request.args.get("scenario", None)
        if scenario == "All":
            scenario = None
        search = request.args.get("search", None)

        # Enforce max limit
        if limit > 500:
            limit = 500

        data = fetch_events(
            limit=limit,
            offset=offset,
            time_range=range_arg,
            start_date=start_date,
            end_date=end_date,
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
        return jsonify({"ok": False, "error": "db_unavailable"}), 503


@app.route("/api/events/export")
@role_required("it_specialist")
def api_events_export_route():
    """
    Stream full raw dataset export (CSV or JSON) respecting all active filters.
    IT Specialist-only.
    """
    try:
        format_type = request.args.get("format", "csv").lower()
        if format_type not in ("csv", "json"):
            return jsonify({"ok": False, "error": "invalid_format", "message": "Format must be 'csv' or 'json'"}), 400

        range_arg = request.args.get("range", "all")
        start_date = request.args.get("start_date") or request.args.get("start")
        end_date = request.args.get("end_date") or request.args.get("end")
        warning_only = request.args.get("warning_only", "false").lower() in ("true", "1")
        in_roi_only = request.args.get("in_roi_only", "false").lower() in ("true", "1")
        min_conf = float(request.args.get("min_conf", 0.0))
        scenario = request.args.get("scenario", None)
        if scenario == "All":
            scenario = None
        search = request.args.get("search", None)

        # Filename generation with timestamp and filter indicator
        now_tag = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        if start_date or end_date:
            range_tag = "custom"
        else:
            range_tag = range_arg
        
        filename = f"crosswalk_audit_events_{range_tag}_{now_tag}.{format_type}"

        if format_type == "csv":
            def generate_csv():
                output = io.StringIO()
                writer = csv.writer(output)
                # Write CSV header row
                writer.writerow(RAW_EXPORT_FIELDS)
                yield output.getvalue()
                output.seek(0)
                output.truncate(0)

                # Stream matching rows
                for row in stream_events(
                    time_range=range_arg,
                    start_date=start_date,
                    end_date=end_date,
                    warning_only=warning_only,
                    in_roi_only=in_roi_only,
                    min_conf=min_conf,
                    scenario=scenario,
                    search=search
                ):
                    writer.writerow([row.get(f, "") for f in RAW_EXPORT_FIELDS])
                    yield output.getvalue()
                    output.seek(0)
                    output.truncate(0)

            return Response(
                generate_csv(),
                mimetype="text/csv; charset=utf-8",
                headers={
                    "Content-Disposition": f"attachment; filename=\"{filename}\"",
                    "Cache-Control": "no-cache"
                }
            )

        elif format_type == "json":
            def generate_json():
                yield "[\n"
                first = True
                for row in stream_events(
                    time_range=range_arg,
                    start_date=start_date,
                    end_date=end_date,
                    warning_only=warning_only,
                    in_roi_only=in_roi_only,
                    min_conf=min_conf,
                    scenario=scenario,
                    search=search
                ):
                    if not first:
                        yield ",\n"
                    yield "  " + json.dumps(row, default=str)
                    first = False
                yield "\n]"

            return Response(
                generate_json(),
                mimetype="application/json; charset=utf-8",
                headers={
                    "Content-Disposition": f"attachment; filename=\"{filename}\"",
                    "Cache-Control": "no-cache"
                }
            )

    except Exception as e:
        print(f"API EXPORT ERROR: {e}")
        return jsonify({"ok": False, "error": "export_failed", "message": str(e)}), 500

@app.route("/api/analytics")
@login_required
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
# Mode-Switching & Test Video API Routes
# --------------------------------------------------------------------------------

def _stop_active_session():
    """Cleanly stop the currently running session."""
    global active_session
    if active_session is not None:
        try:
            active_session.stop()
        except Exception as e:
            print(f"[MODE] Error stopping session: {e}")
        active_session = None


def _start_live_session():
    """Start a new LiveSession with the Hikvision RTSP URL."""
    global active_session, current_mode
    _stop_active_session()
    if not HIKVISION_RTSP_URL:
        print("[MODE] Cannot start live — HIKVISION_RTSP_URL not configured")
        return False
    active_session = LiveSession(
        rtsp_url=HIKVISION_RTSP_URL,
        reconnect_sec=HIKVISION_RECONNECT_SEC,
    )
    active_session.start()
    current_mode = "live"
    print("[MODE] Switched to LIVE mode")
    return True


def _start_video_test_session(filename: str):
    """Start a new VideoTestSession with the given .mp4 file."""
    global active_session, current_mode
    video_path = TEST_VIDEOS_DIR / filename
    if not video_path.exists() or not video_path.is_file():
        print(f"[MODE] Video not found: {video_path}")
        return False
    _stop_active_session()
    active_session = VideoTestSession(video_path=str(video_path))
    active_session.start()
    current_mode = "video_test"
    print(f"[MODE] Switched to VIDEO TEST mode: {filename}")
    return True


@app.get("/api/mode")
@login_required
def api_get_mode():
    """Return the current operating mode."""
    info = {"ok": True, "mode": current_mode}
    if current_mode == "video_test" and active_session and hasattr(active_session, '_video_filename'):
        info["video_filename"] = active_session._video_filename
    return jsonify(info)


@app.post("/api/mode/live")
@role_required("tmc_officer")
def api_switch_to_live():
    """Switch to live camera mode (TMC Officer only)."""
    with _session_lock:
        ok = _start_live_session()
    if ok:
        socketio.emit("mode_update", {"mode": "live"})
        return jsonify({"ok": True, "mode": "live"})
    return jsonify({"ok": False, "error": "RTSP URL not configured"}), 400


@app.post("/api/mode/video_test")
@role_required("tmc_officer")
def api_switch_to_video_test():
    """Switch to video test mode with a specific .mp4 file (TMC Officer only)."""
    data = request.get_json(silent=True) or {}
    filename = data.get("filename", "").strip()
    if not filename:
        return jsonify({"ok": False, "error": "No filename provided"}), 400

    # Security: prevent path traversal
    if ".." in filename or "/" in filename or "\\" in filename:
        return jsonify({"ok": False, "error": "Invalid filename"}), 400

    with _session_lock:
        ok = _start_video_test_session(filename)
    if ok:
        socketio.emit("mode_update", {"mode": "video_test", "video_filename": filename})
        return jsonify({"ok": True, "mode": "video_test", "video_filename": filename})
    return jsonify({"ok": False, "error": "Video file not found"}), 404


@app.get("/api/test_videos")
@role_required("tmc_officer")
def api_list_test_videos():
    """List all .mp4 files available in the test_videos/ directory."""
    videos = []
    for f in sorted(TEST_VIDEOS_DIR.glob("*.mp4")):
        try:
            cap = cv2.VideoCapture(str(f), cv2.CAP_FFMPEG)
            fps = cap.get(cv2.CAP_PROP_FPS) or 0
            total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
            duration = (total / fps) if fps > 0 else 0
            w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH) or 0)
            h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT) or 0)
            cap.release()
            videos.append({
                "filename": f.name,
                "size_mb": round(f.stat().st_size / (1024 * 1024), 1),
                "duration_sec": round(duration, 1),
                "fps": round(fps, 1),
                "resolution": f"{w}x{h}" if w > 0 else "unknown",
                "total_frames": total,
            })
        except Exception:
            videos.append({"filename": f.name, "size_mb": round(f.stat().st_size / (1024 * 1024), 1)})
    return jsonify({"ok": True, "videos": videos})


@app.post("/api/test_videos/upload")
@role_required("tmc_officer")
def api_upload_test_video():
    """Upload a new .mp4 file to the test_videos/ directory."""
    if "file" not in request.files:
        return jsonify({"ok": False, "error": "No file in request"}), 400

    file = request.files["file"]
    if not file.filename:
        return jsonify({"ok": False, "error": "No filename"}), 400

    # Validate extension
    if not file.filename.lower().endswith(".mp4"):
        return jsonify({"ok": False, "error": "Only .mp4 files are accepted"}), 400

    # Security: sanitize filename
    safe_name = Path(file.filename).name
    if ".." in safe_name or "/" in safe_name or "\\" in safe_name:
        return jsonify({"ok": False, "error": "Invalid filename"}), 400

    dest = TEST_VIDEOS_DIR / safe_name
    try:
        file.save(str(dest))
        size_mb = round(dest.stat().st_size / (1024 * 1024), 1)
        print(f"[UPLOAD] Saved test video: {safe_name} ({size_mb} MB)")
        return jsonify({"ok": True, "filename": safe_name, "size_mb": size_mb})
    except Exception as e:
        # Clean up partial file
        if dest.exists():
            dest.unlink()
        return jsonify({"ok": False, "error": str(e)}), 500


# --------------------------------------------------------------------------------
# Entry Point
# --------------------------------------------------------------------------------
if __name__ == "__main__":
    # Initialize DB (safe to run multiple times)
    init_db()

    # Set max upload size for video files
    app.config["MAX_CONTENT_LENGTH"] = TEST_VIDEO_MAX_UPLOAD_MB * 1024 * 1024

    # Auto-start Hikvision CCTV session on boot
    if HIKVISION_RTSP_URL:
        active_session = LiveSession(
            rtsp_url=HIKVISION_RTSP_URL,
            reconnect_sec=HIKVISION_RECONNECT_SEC,
        )
        active_session.start()
        current_mode = "live"
        print(f"[BOOT] Hikvision session auto-started (LIVE mode)")
    else:
        print("[BOOT] WARNING: HIKVISION_RTSP_URL not set — camera disabled")

    # Run the Flask-SocketIO server.
    socketio.run(app, host="0.0.0.0", port=5000, debug=True, allow_unsafe_werkzeug=True)


