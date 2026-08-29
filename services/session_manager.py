"""
session_manager.py — Centralised active-session state manager.

Replaces the scattered ``global active_session`` / ``global current_mode``
pattern from monolithic ``app.py`` with a single thread-safe manager.

Usage (from routes or sockets)::

    from services.session_manager import session_mgr

    session_mgr.get_active()          # → LiveSession | VideoTestSession | None
    session_mgr.get_mode()            # → "live" | "video_test"
    session_mgr.start_live()          # → bool
    session_mgr.start_video_test(fn)  # → bool
    session_mgr.stop()                # stops the current session
"""

import threading
from typing import Optional

from config import HIKVISION_RTSP_URL, HIKVISION_RECONNECT_SEC, TEST_VIDEOS_DIR
from services.live_session import LiveSession
from services.video_test_session import VideoTestSession


class SessionManager:
    """Thread-safe wrapper around the active detection session."""

    def __init__(self):
        self._lock = threading.Lock()
        self._active: Optional[LiveSession] = None
        self._mode: str = "live"

    # ── Accessors ────────────────────────────────────────────────────────

    def get_active(self) -> Optional[LiveSession]:
        """Return the currently active session (or None if idle)."""
        return self._active

    def get_mode(self) -> str:
        """Return the current operating mode ('live' or 'video_test')."""
        return self._mode

    # ── Lifecycle ────────────────────────────────────────────────────────

    def stop(self):
        """Cleanly stop the currently running session."""
        with self._lock:
            if self._active is not None:
                try:
                    self._active.stop()
                except Exception as e:
                    print(f"[MODE] Error stopping session: {e}")
                self._active = None

    def start_live(self) -> bool:
        """Start a new LiveSession with the Hikvision RTSP URL."""
        with self._lock:
            self._stop_unlocked()
            if not HIKVISION_RTSP_URL:
                print("[MODE] Cannot start live — HIKVISION_RTSP_URL not configured")
                return False
            self._active = LiveSession(
                rtsp_url=HIKVISION_RTSP_URL,
                reconnect_sec=HIKVISION_RECONNECT_SEC,
            )
            self._active.start()
            self._mode = "live"
            print("[MODE] Switched to LIVE mode")
            return True

    def start_video_test(self, filename: str) -> bool:
        """Start a new VideoTestSession with the given .mp4 file."""
        with self._lock:
            video_path = TEST_VIDEOS_DIR / filename
            if not video_path.exists() or not video_path.is_file():
                print(f"[MODE] Video not found: {video_path}")
                return False
            self._stop_unlocked()
            self._active = VideoTestSession(video_path=str(video_path))
            self._active.start()
            self._mode = "video_test"
            print(f"[MODE] Switched to VIDEO TEST mode: {filename}")
            return True

    def auto_start_live(self):
        """Auto-start live RTSP session on boot (called from app factory)."""
        if HIKVISION_RTSP_URL:
            self._active = LiveSession(
                rtsp_url=HIKVISION_RTSP_URL,
                reconnect_sec=HIKVISION_RECONNECT_SEC,
            )
            self._active.start()
            self._mode = "live"
            print(f"[BOOT] Hikvision session auto-started (LIVE mode)")
        else:
            print("[BOOT] WARNING: HIKVISION_RTSP_URL not set — camera disabled")

    # ── Internal ─────────────────────────────────────────────────────────

    def _stop_unlocked(self):
        """Stop the active session (caller must already hold _lock)."""
        if self._active is not None:
            try:
                self._active.stop()
            except Exception as e:
                print(f"[MODE] Error stopping session: {e}")
            self._active = None


# Module-level singleton — import this everywhere
session_mgr = SessionManager()
