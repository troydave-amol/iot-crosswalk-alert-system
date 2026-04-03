import os
import threading
import time
from datetime import datetime, timezone
from typing import Optional, Union

from dotenv import load_dotenv
from flask import Flask, render_template, request, jsonify, Response
from flask_socketio import SocketIO

import cv2
import json
from pathlib import Path
from cv_inference import ChildLikeDetector, ROI
from warning_controller import TemporalVoteStabilizer, WarningController
from detection_tracker import DetectionTracker

load_dotenv()

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
TRACKER_MAX_MISSES = _env_int("TRACKER_MAX_MISSES", 5)
TRACKER_SMOOTH_ALPHA = _env_float("TRACKER_SMOOTH_ALPHA", 0.6)

MODEL_PATH = _resolve_model_path()

# Hikvision CCTV — single fixed camera source (auto-connect on boot)
HIKVISION_RTSP_URL = (os.getenv("HIKVISION_RTSP_URL") or "").strip()
HIKVISION_RECONNECT_SEC = _env_float("HIKVISION_RECONNECT_SEC", 5.0)

# FFMPEG low-latency flags for RTSP capture (must be set before VideoCapture)
# - rtsp_transport=tcp: reliable delivery (same as Hikvision's own viewer)
# - fflags=nobuffer: don't buffer input packets
# - flags=low_delay: minimize decode latency
# - analyzeduration/probesize: start decoding faster
os.environ["OPENCV_FFMPEG_CAPTURE_OPTIONS"] = (
    "rtsp_transport;tcp|fflags;nobuffer|flags;low_delay|analyzeduration;100000|probesize;100000"
)


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
    Sends the current camera status so the dashboard shows the real state.
    """
    print("Client connected")
    # Send current camera status immediately
    if hikvision_session is not None:
        cam_status = "OK" if hikvision_session.camera_online else "OFFLINE"
        socketio.emit("status_update", _build_idle_payload(camera_status=cam_status))
        socketio.emit("camera_status", hikvision_session.get_status())
    else:
        socketio.emit("status_update", _build_idle_payload(camera_status="OFFLINE"))

# --------------------------------------------------------------------------------
# Live Pipeline
# --------------------------------------------------------------------------------

# (Multi-source camera helpers removed — Hikvision is the sole source)


def _build_idle_payload(camera_status: str, edge_status: str = "OK") -> dict:
    return {
        "timestamp_iso": datetime.now(timezone.utc).isoformat(),
        "child_in_roi": False,
        "child_in_roi_raw": False,
        "roi_status": "CLEAR",
        "confidence": 0.0,
        "confidence_raw": 0.0,
        "latency_ms": 0,
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
        cv2.rectangle(roi_overlay, (roi.x1, roi.y1), (roi.x2, roi.y2), fill_color, -1)
        cv2.addWeighted(roi_overlay, 0.08, frame, 0.92, 0, frame)
        cv2.rectangle(frame, (roi.x1, roi.y1), (roi.x2, roi.y2), border_color, 4)

        roi_label = "ROI: CHILD DETECTED" if child_in_roi else "ROI: CLEAR"
        (tw, th), _ = cv2.getTextSize(roi_label, cv2.FONT_HERSHEY_SIMPLEX, 0.8, 2)
        lx, ly = roi.x1, max(th + 10, roi.y1 - 10)
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
            )
            self.detector_error = None
        except Exception as exc:
            self.detector = None
            self.detector_error = f"{type(exc).__name__}: {exc}"
            print(f"[LIVE] Detector load failed | {self.detector_error}")

    def get_status(self) -> dict:
        """Return a snapshot of camera/AI status for the dashboard."""
        return {
            "camera_online": self.camera_online,
            "stream_connected": self.stream_connected,
            "ai_running": self.detector is not None,
            "ai_error": self.detector_error,
            "reconnect_attempts": self.reconnect_attempts,
            "last_frame_time": self.last_frame_time,
            "rtsp_url_masked": self._mask_url(self.rtsp_url),
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

            with self.state_lock:
                self.latest_frame_raw = frame
            self.last_frame_time = time.time()
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

            for d in tracked_detections:
                if d["cls"] == 1 and d["conf"] >= CHILD_CONF:
                    x1, y1, x2, y2 = d["bbox"]
                    if (y2 - y1) >= min_bbox_h:
                        cx = (x1 + x2) / 2.0
                        # Check strictly bottom-center like cv_inference does
                        if roi.contains_point(cx, float(y2)):
                            tracked_child_in_roi_raw = True
                            tracked_confidence_raw = max(tracked_confidence_raw, d["conf"])

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
                "detections": tracked_detections,
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


# Singleton Hikvision session — initialized at startup
hikvision_session: Optional[LiveSession] = None


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
def video_feed_route():
    """MJPEG stream from the single Hikvision session (always-on)."""
    overlay = request.args.get("overlay", "1") == "1"
    if hikvision_session is None:
        return Response("Camera not configured", status=503)
    return Response(
        gen_frames(hikvision_session, overlay=overlay),
        mimetype="multipart/x-mixed-replace; boundary=frame",
    )


@app.get("/api/camera/snapshot")
def api_camera_snapshot():
    """Return a single JPEG frame from the live camera (full resolution, no overlay).
    Used by the ROI 'Capture Frame' button."""
    if hikvision_session is None:
        return Response("Camera not configured", status=503)

    frame = hikvision_session.get_stream_frame(overlay=False)
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
def api_camera_status():
    """Returns the current Hikvision camera / AI pipeline status."""
    if hikvision_session is None:
        return jsonify({
            "ok": True,
            "camera_online": False,
            "stream_connected": False,
            "ai_running": False,
            "ai_error": "No HIKVISION_RTSP_URL configured",
            "reconnect_attempts": 0,
            "last_frame_time": 0,
            "rtsp_url_masked": "",
        })
    return jsonify({"ok": True, **hikvision_session.get_status()})


@app.post("/api/camera/reconnect")
def api_camera_reconnect():
    """Force the Hikvision session to reconnect (only if actually broken)."""
    if hikvision_session is None:
        return jsonify({"ok": False, "error": "No session"}), 503

    # If camera is already online and streaming, don't destroy the connection.
    # Just return OK so the frontend can safely re-attach.
    if hikvision_session.camera_online and hikvision_session.stream_connected:
        print("[LIVE] Reconnect requested but camera is already online — skipping")
        return jsonify({"ok": True, "action": "already_online"})

    # Camera is genuinely offline/broken — force reconnect
    if hikvision_session.cap is not None:
        try:
            hikvision_session.cap.release()
        except Exception:
            pass
        hikvision_session.cap = None
    hikvision_session.camera_online = False
    hikvision_session.stream_connected = False
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

    # Auto-start Hikvision CCTV session on boot
    if HIKVISION_RTSP_URL:
        hikvision_session = LiveSession(
            rtsp_url=HIKVISION_RTSP_URL,
            reconnect_sec=HIKVISION_RECONNECT_SEC,
        )
        hikvision_session.start()
        print(f"[BOOT] Hikvision session auto-started")
    else:
        print("[BOOT] WARNING: HIKVISION_RTSP_URL not set — camera disabled")

    # Run the Flask-SocketIO server.
    socketio.run(app, host="0.0.0.0", port=5000, debug=True, allow_unsafe_werkzeug=True)


