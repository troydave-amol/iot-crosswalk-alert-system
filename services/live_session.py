"""
live_session.py — RTSP camera capture and YOLO inference pipeline.

Contains the ``LiveSession`` class that manages:
- Background capture thread (auto-connect, auto-reconnect)
- Background inference thread (YOLO detection, tracking, vote stabilization)
- ESP32 relay control
- Database event logging
- Socket.IO telemetry emission

Also provides ``build_idle_payload()`` for emitting idle state to dashboards.
"""

import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import cv2

from config import (
    MODEL_PATH, CHILD_CONF, MIN_CHILD_BBOX_RATIO, DOMINANCE_IOU,
    WARNING_HOLD_SECONDS, WARNING_MIN_TOGGLE_SEC, YOLO_IMGSZ,
    INFER_INTERVAL_SEC, CAM_WIDTH, CAM_HEIGHT,
    TRACKER_IOU_THRESHOLD, TRACKER_MAX_MISSES, TRACKER_SMOOTH_ALPHA,
    TRACKER_CONF_SMOOTH_ALPHA, CLASS_SWITCH_FRAMES, FEET_HEIGHT_RATIO,
    ROI_PATH, get_time_scenario,
)
from cv_inference import ChildLikeDetector, ROI
from db import insert_event
from detection_tracker import DetectionTracker
from extensions import socketio
from services.edge_metrics import get_edge_compute_metrics
from services.hardware import esp32_relay
from services.overlay_renderer import draw_overlay
from services.roi_manager import load_roi_for_frame
from warning_controller import TemporalVoteStabilizer, WarningController


def _emit_camera_status(session):
    """Push camera status to all connected dashboard clients."""
    try:
        socketio.emit("camera_status", session.get_status())
    except Exception:
        pass


def build_idle_payload(camera_status: str, edge_status: str = "OK") -> dict:
    """Build a status_update payload for idle/offline state."""
    relay_diag = esp32_relay.get_diagnostics()
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
        relay_diag = esp32_relay.get_diagnostics()
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
            f"| stream_fps={0:.1f} | infer_interval={INFER_INTERVAL_SEC:.3f}s "
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
                payload = build_idle_payload(camera_status="OK", edge_status="ERROR")
                socketio.emit("status_update", payload)
                annotated = draw_overlay(
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

            annotated = draw_overlay(
                frame.copy(),
                roi,
                out.get("detections", []),
                out["child_in_roi"],
            )
            with self.state_lock:
                self.latest_frame_annotated = annotated

            self.infer_frames += 1
            self._log_perf(last_latency_ms=out["latency_ms"])
