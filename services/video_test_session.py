"""
video_test_session.py — MP4 video test pipeline.

Inherits from ``LiveSession`` and overrides only the capture loop
and database logging to play back a pre-recorded video file through
the same YOLO inference, tracking, warning, and overlay pipeline.
"""

import time
from pathlib import Path

import cv2

from config import (
    TEST_VIDEO_FPS,
    TRACKER_IOU_THRESHOLD, TRACKER_MAX_MISSES, TRACKER_SMOOTH_ALPHA,
    TRACKER_CONF_SMOOTH_ALPHA, CLASS_SWITCH_FRAMES,
    get_time_scenario,
)
from db import insert_event
from detection_tracker import DetectionTracker
from services.edge_metrics import get_edge_compute_metrics
from services.hardware import esp32_relay
from services.live_session import LiveSession, _emit_camera_status


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
