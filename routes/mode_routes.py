"""
mode_routes.py — Mode switching and test video management endpoints.

Blueprint: ``mode_bp``
Routes:
    GET  /api/mode              → current operating mode
    POST /api/mode/live         → switch to live RTSP (TMC only)
    POST /api/mode/video_test   → switch to video test (TMC only)
    GET  /api/test_videos       → list available test videos (TMC only)
    POST /api/test_videos/upload → upload a new test video (TMC only)
"""

from pathlib import Path

import cv2
from flask import Blueprint, request, jsonify

from auth.decorators import login_required, role_required
from config import TEST_VIDEOS_DIR
from extensions import socketio
from services.session_manager import session_mgr

mode_bp = Blueprint("mode", __name__)


@mode_bp.get("/api/mode")
@login_required
def api_get_mode():
    """Return the current operating mode."""
    mode = session_mgr.get_mode()
    active = session_mgr.get_active()
    info = {"ok": True, "mode": mode}
    if mode == "video_test" and active and hasattr(active, '_video_filename'):
        info["video_filename"] = active._video_filename
    return jsonify(info)


@mode_bp.post("/api/mode/live")
@role_required("tmc_officer")
def api_switch_to_live():
    """Switch to live camera mode (TMC Officer only)."""
    ok = session_mgr.start_live()
    if ok:
        socketio.emit("mode_update", {"mode": "live"})
        return jsonify({"ok": True, "mode": "live"})
    return jsonify({"ok": False, "error": "RTSP URL not configured"}), 400


@mode_bp.post("/api/mode/video_test")
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

    ok = session_mgr.start_video_test(filename)
    if ok:
        socketio.emit("mode_update", {"mode": "video_test", "video_filename": filename})
        return jsonify({"ok": True, "mode": "video_test", "video_filename": filename})
    return jsonify({"ok": False, "error": "Video file not found"}), 404


@mode_bp.get("/api/test_videos")
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


@mode_bp.post("/api/test_videos/upload")
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
