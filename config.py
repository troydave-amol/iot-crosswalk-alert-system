"""
config.py — Centralised runtime configuration for the crosswalk alert system.

Reads all tunable parameters from the ``.env`` file via ``os.environ``.
Nothing in this module imports app-specific modules (Flask app, db, etc.),
so it is safe to import from anywhere without circular-dependency risk.

Exports
-------
- Helper functions: ``_env_float``, ``_env_int``, ``_resolve_model_path``
- Time-scenario utility: ``get_time_scenario``
- Module-level constants grouped by concern (detection, tracker, camera, etc.)
"""

import os
from datetime import datetime, timezone, timedelta, time as dt_time
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

# ────────────────────────────────────────────────────────────────────────────
# Helpers
# ────────────────────────────────────────────────────────────────────────────

PROJECT_ROOT = Path(__file__).resolve().parent
DEFAULT_MODEL_PATH = PROJECT_ROOT / "models" / "yolov8n_1500_frames.pt"
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


# ────────────────────────────────────────────────────────────────────────────
# Detection Pipeline Thresholds
# ────────────────────────────────────────────────────────────────────────────
CHILD_CONF              = _env_float("LIVE_CHILD_CONF", 0.65)
MIN_CHILD_BBOX_RATIO    = _env_float("LIVE_MIN_CHILD_BBOX_RATIO", 0.18)
DOMINANCE_IOU           = _env_float("LIVE_DOMINANCE_IOU", 0.70)
WARNING_HOLD_SECONDS    = _env_float("LIVE_WARNING_HOLD_SECONDS", 3.5)
WARNING_MIN_TOGGLE_SEC  = _env_float("LIVE_WARNING_MIN_TOGGLE_SEC", 0.75)
YOLO_IMGSZ              = _env_int("LIVE_YOLO_IMGSZ", 640)
INFER_INTERVAL_SEC      = _env_float("LIVE_INFER_INTERVAL_SEC", 0.125)
STREAM_FPS              = max(1.0, _env_float("LIVE_STREAM_FPS", 25.0))
STREAM_SCALE            = max(0.1, min(1.0, _env_float("LIVE_STREAM_SCALE", 0.5)))  # downscale for MJPEG only
CAM_WIDTH               = _env_int("LIVE_CAM_WIDTH", 640)
CAM_HEIGHT              = _env_int("LIVE_CAM_HEIGHT", 360)

# Anti-Flicker Tracker Settings
TRACKER_IOU_THRESHOLD      = _env_float("TRACKER_IOU_THRESHOLD", 0.25)
TRACKER_MAX_MISSES         = _env_int("TRACKER_MAX_MISSES", 25)
TRACKER_SMOOTH_ALPHA       = _env_float("TRACKER_SMOOTH_ALPHA", 0.6)
TRACKER_CONF_SMOOTH_ALPHA  = _env_float("TRACKER_CONF_SMOOTH_ALPHA", 0.4)
CLASS_SWITCH_FRAMES        = _env_int("CLASS_SWITCH_FRAMES", 15)  # consecutive opposing frames to switch label

# Feet-zone detection — only the bottom portion of the child bbox is checked against ROI
FEET_HEIGHT_RATIO = _env_float("FEET_HEIGHT_RATIO", 0.15)


# ────────────────────────────────────────────────────────────────────────────
# Model & Video Testing
# ────────────────────────────────────────────────────────────────────────────
MODEL_PATH = _resolve_model_path()

TEST_VIDEO_FPS          = _env_float("TEST_VIDEO_FPS", 0)
TEST_VIDEO_MAX_UPLOAD_MB = _env_int("TEST_VIDEO_MAX_UPLOAD_MB", 500)
TEST_VIDEOS_DIR         = PROJECT_ROOT / "test_videos"
TEST_VIDEOS_DIR.mkdir(exist_ok=True)

# ────────────────────────────────────────────────────────────────────────────
# Hikvision CCTV — single fixed camera source (auto-connect on boot)
# ────────────────────────────────────────────────────────────────────────────
HIKVISION_RTSP_URL     = (os.getenv("HIKVISION_RTSP_URL") or "").strip()
HIKVISION_RECONNECT_SEC = _env_float("HIKVISION_RECONNECT_SEC", 5.0)

# ────────────────────────────────────────────────────────────────────────────
# ESP32 Warning Relay
# ────────────────────────────────────────────────────────────────────────────
ESP32_ENABLED = os.getenv("ESP32_ENABLED", "false").strip().lower() in ("true", "1", "yes")
ESP32_PORT    = (os.getenv("ESP32_PORT") or "COM5").strip()
ESP32_BAUD    = _env_int("ESP32_BAUD", 115200)

# ────────────────────────────────────────────────────────────────────────────
# FFMPEG low-latency flags for RTSP capture (must be set before VideoCapture)
# ────────────────────────────────────────────────────────────────────────────
# - rtsp_transport=tcp: reliable delivery (same as Hikvision's own viewer)
# - fflags=nobuffer: don't buffer input packets
# - flags=low_delay: minimize decode latency
# - analyzeduration/probesize: start decoding faster
os.environ["OPENCV_FFMPEG_CAPTURE_OPTIONS"] = (
    "rtsp_transport;tcp|fflags;nobuffer|flags;low_delay|analyzeduration;100000|probesize;100000"
)
