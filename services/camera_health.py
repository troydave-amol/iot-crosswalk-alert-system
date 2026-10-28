"""
camera_health.py — Independent camera & stream health monitor.

Runs a background thread that:
  1. Probes the physical RTSP camera via a short-timeout TCP connect
     (host:port only — no credentials sent, none included in any payload).
  2. Tracks the stream feed via a last-frame watchdog against the active session.
  3. Publishes a unified ``camera_health`` Socket.IO event every probe interval.
  4. Debounces consecutive failures before declaring Offline to prevent flapping.

This is the single source of truth for camera/stream status.
``camera_online`` / ``stream_connected`` on LiveSession/VideoTestSession are
**not** used for UI status anymore — they now only gate the capture loop.

Singleton: import ``camera_health_monitor`` everywhere.
"""

from __future__ import annotations

import socket
import threading
import time
from datetime import datetime, timezone
from typing import Optional
from urllib.parse import urlparse

from config import HIKVISION_RTSP_URL
from extensions import socketio


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
_PROBE_INTERVAL_SEC = 5.0       # how often to probe the camera
_TCP_TIMEOUT_SEC = 2.0          # TCP connect timeout per probe attempt
_DEBOUNCE_FAILURES = 3          # consecutive failures needed to go Offline
_STALE_THRESHOLD_SEC = 3.0      # seconds without a frame → "Stalled"
_NO_SIGNAL_THRESHOLD_SEC = 15.0 # seconds without a frame → "No Signal"
_STALENESS_EXPIRE_SEC = 12.0    # seconds without camera_health emit → show "Unknown" on UI


class CameraHealthMonitor:
    """
    Background thread that independently probes the RTSP camera (TCP only)
    and tracks stream feed freshness via the active session's last_frame_time.

    Never blocks the detection pipeline.
    Never exposes RTSP credentials in any payload, log, or UI string.
    """

    def __init__(self):
        self._lock = threading.Lock()
        self._stop_event = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._trigger_event = threading.Event()  # for on-demand checks

        # Parse host:port from RTSP URL (credentials stripped here, never stored)
        self._rtsp_host, self._rtsp_port = self._parse_rtsp_endpoint(HIKVISION_RTSP_URL)

        # State
        self._camera_state: str = "Unknown"   # Unknown / Online / Offline / Not configured
        self._stream_state: str = "Unknown"   # Unknown / Receiving / Stalled / No Signal / Simulation / Idle
        self._source_mode: str = "none"       # live / video_test / none
        self._last_frame_age_s: float = -1.0
        self._last_checked_iso: str = ""
        self._consecutive_failures: int = 0
        self._started: bool = False

    # -----------------------------------------------------------------------
    # Public API
    # -----------------------------------------------------------------------

    def start(self):
        """Start the background probe thread."""
        if self._started:
            return
        self._started = True
        self._thread = threading.Thread(
            target=self._probe_loop,
            name="camera-health-monitor",
            daemon=True,
        )
        self._thread.start()
        print("[CAM_HEALTH] Monitor started"
              + (f" — probing {self._rtsp_host}:{self._rtsp_port}"
                 if self._rtsp_host else " — no RTSP URL configured"))

    def stop(self):
        """Signal the probe loop to exit."""
        self._stop_event.set()

    def trigger_check(self):
        """Trigger an immediate probe (e.g. on Reconnect button click)."""
        self._trigger_event.set()

    def get_health(self) -> dict:
        """Return the latest health snapshot (thread-safe)."""
        with self._lock:
            return {
                "source_mode": self._source_mode,
                "camera_state": self._camera_state,
                "stream_state": self._stream_state,
                "last_frame_age_s": self._last_frame_age_s,
                "last_checked_iso": self._last_checked_iso,
            }

    # -----------------------------------------------------------------------
    # Internal
    # -----------------------------------------------------------------------

    @staticmethod
    def _parse_rtsp_endpoint(url: str) -> tuple[str, int]:
        """
        Extract (host, port) from an RTSP URL.
        Credentials are never stored — they are discarded here.
        Returns ("", 0) if URL is empty or unparseable.
        """
        url = (url or "").strip()
        if not url:
            return "", 0
        try:
            parsed = urlparse(url)
            host = parsed.hostname or ""
            port = parsed.port or 554
            return host, int(port)
        except Exception:
            return "", 0

    def _probe_camera_tcp(self) -> bool:
        """
        Short-timeout TCP connect to the RTSP host:port.
        Returns True if the port is reachable, False otherwise.
        No credentials are sent.
        """
        if not self._rtsp_host:
            return False
        try:
            with socket.create_connection(
                (self._rtsp_host, self._rtsp_port),
                timeout=_TCP_TIMEOUT_SEC,
            ):
                return True
        except (OSError, ConnectionRefusedError, TimeoutError):
            return False

    def _compute_stream_state(self, source_mode: str, active_session) -> tuple[str, float]:
        """
        Determine stream_state and last_frame_age_s from the active session.
        Never touches camera_state — those are separate concerns.
        """
        if source_mode == "video_test":
            return "Simulation", -1.0

        if source_mode == "none" or active_session is None:
            return "Idle", -1.0

        # Live mode: check last_frame_time
        last_t = getattr(active_session, "last_frame_time", 0.0)
        if last_t <= 0.0:
            return "No Signal", -1.0

        age = time.time() - last_t
        if age < _STALE_THRESHOLD_SEC:
            return "Receiving", round(age, 1)
        elif age < _NO_SIGNAL_THRESHOLD_SEC:
            return "Stalled", round(age, 1)
        else:
            return "No Signal", round(age, 1)

    def _probe_loop(self):
        """Main background loop: probe camera + assess stream every N seconds."""
        # Lazy import to avoid circular dependency
        from services.session_manager import session_mgr

        while not self._stop_event.is_set():
            try:
                self._run_one_probe(session_mgr)
            except Exception as exc:
                print(f"[CAM_HEALTH] Probe error: {exc}")

            # Wait for next interval or an on-demand trigger
            self._trigger_event.wait(timeout=_PROBE_INTERVAL_SEC)
            self._trigger_event.clear()

    def _run_one_probe(self, session_mgr):
        """Execute one probe cycle and emit the result."""
        mode = session_mgr.get_mode()
        active = session_mgr.get_active()

        # Determine source_mode (none if no active session)
        if active is None:
            source_mode = "none"
        else:
            source_mode = mode  # "live" or "video_test"

        # ── Camera state (physical device reachability) ──────────────────
        if not self._rtsp_host:
            camera_state = "Not configured"
            # Reset failure counter — not applicable
            self._consecutive_failures = 0
        else:
            reachable = self._probe_camera_tcp()
            if reachable:
                self._consecutive_failures = 0
                camera_state = "Online"
            else:
                self._consecutive_failures += 1
                if self._consecutive_failures >= _DEBOUNCE_FAILURES:
                    camera_state = "Offline"
                else:
                    # Keep last known state during debounce window
                    camera_state = self._camera_state if self._camera_state not in ("Unknown",) else "Offline"

        # ── Stream state (feed freshness) ─────────────────────────────────
        stream_state, frame_age = self._compute_stream_state(source_mode, active)

        # ── Timestamp ─────────────────────────────────────────────────────
        checked_iso = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

        # ── Update internal state (thread-safe) ───────────────────────────
        with self._lock:
            self._source_mode = source_mode
            self._camera_state = camera_state
            self._stream_state = stream_state
            self._last_frame_age_s = frame_age
            self._last_checked_iso = checked_iso

        # ── Emit to all connected dashboard clients ───────────────────────
        payload = {
            "source_mode": source_mode,
            "camera_state": camera_state,
            "stream_state": stream_state,
            "last_frame_age_s": frame_age,
            "last_checked_iso": checked_iso,
        }
        try:
            socketio.emit("camera_health", payload)
        except Exception as exc:
            print(f"[CAM_HEALTH] Emit error: {exc}")

        print(
            f"[CAM_HEALTH] mode={source_mode} cam={camera_state} stream={stream_state}"
            + (f" age={frame_age}s" if frame_age >= 0 else "")
            + (f" (fail#{self._consecutive_failures})" if self._consecutive_failures > 0 else "")
        )


# ---------------------------------------------------------------------------
# Module-level singleton
# ---------------------------------------------------------------------------
camera_health_monitor = CameraHealthMonitor()
