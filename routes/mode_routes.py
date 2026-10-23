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
from config import TEST_VIDEOS_DIR, TEST_VIDEO_FOLDER_MAPPING
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


# In-memory video metadata cache to avoid slow repeated cv2 re-reads
_VIDEO_META_CACHE = {}


@mode_bp.post("/api/mode/video_test")
@role_required("tmc_officer")
def api_switch_to_video_test():
    """Switch to video test mode with a specific .mp4 file (supports nested folder paths)."""
    data = request.get_json(silent=True) or {}
    filename = (data.get("filename") or data.get("path") or "").strip()
    if not filename:
        return jsonify({"ok": False, "error": "No filename provided"}), 400

    # Normalize backslashes to forward slashes and strip leading/trailing slashes
    rel_path_str = filename.replace("\\", "/").strip().lstrip("/")

    # Security: prevent path traversal
    parts = Path(rel_path_str).parts
    if any(p == ".." for p in parts):
        return jsonify({"ok": False, "error": "Invalid filename"}), 400

    target_path = (TEST_VIDEOS_DIR / rel_path_str).resolve()
    try:
        if not target_path.is_relative_to(TEST_VIDEOS_DIR.resolve()):
            return jsonify({"ok": False, "error": "Access denied"}), 403
    except AttributeError:
        if not str(target_path).startswith(str(TEST_VIDEOS_DIR.resolve())):
            return jsonify({"ok": False, "error": "Access denied"}), 403

    if not target_path.is_file():
        # Fallback: maybe only the file basename was provided, search for it
        matches = [m for m in TEST_VIDEOS_DIR.rglob(Path(rel_path_str).name) if m.is_file()]
        if matches:
            target_path = matches[0]
        else:
            return jsonify({"ok": False, "error": "Video file not found"}), 404

    rel_key = target_path.relative_to(TEST_VIDEOS_DIR).as_posix()
    ok = session_mgr.start_video_test(rel_key)
    if ok:
        socketio.emit("mode_update", {"mode": "video_test", "video_filename": rel_key})
        return jsonify({"ok": True, "mode": "video_test", "video_filename": rel_key})
    return jsonify({"ok": False, "error": "Failed to start video test"}), 500


def get_test_video_folder(rel_file_path: Path) -> str:
    """Return the relative parent folder of a test video file."""
    try:
        rel_parent = rel_file_path.relative_to(TEST_VIDEOS_DIR).parent.as_posix()
        if rel_parent != ".":
            return rel_parent
    except Exception:
        pass

    filename = rel_file_path.name
    if filename in TEST_VIDEO_FOLDER_MAPPING:
        return TEST_VIDEO_FOLDER_MAPPING[filename]

    clean = filename.strip()
    lower = clean.lower()
    if lower.startswith("morning"):
        return "Morning"
    if lower.startswith("early afternoon") or lower.startswith("early_afternoon") or lower.startswith("early-afternoon"):
        return "Early Afternoon"
    if lower.startswith("late afternoon") or lower.startswith("late_afternoon") or lower.startswith("late-afternoon"):
        return "Late Afternoon"

    return ""


@mode_bp.get("/api/test_videos")
@role_required("tmc_officer")
def api_list_test_videos():
    """List all .mp4 files and folder directory structure available in test_videos/."""
    videos = []
    folders_set = set()

    for f in sorted(TEST_VIDEOS_DIR.rglob("*.mp4")):
        if not f.is_file():
            continue
        try:
            rel_path = f.relative_to(TEST_VIDEOS_DIR).as_posix()
            folder_rel = get_test_video_folder(f)

            if folder_rel:
                # Add all directory hierarchy components
                cur_parent = Path(folder_rel)
                while str(cur_parent) != ".":
                    folders_set.add(cur_parent.as_posix())
                    cur_parent = cur_parent.parent

            st = f.stat()
            cache_key = (rel_path, st.st_mtime, st.st_size)
            if cache_key in _VIDEO_META_CACHE:
                meta = _VIDEO_META_CACHE[cache_key]
            else:
                cap = cv2.VideoCapture(str(f), cv2.CAP_FFMPEG)
                fps = cap.get(cv2.CAP_PROP_FPS) or 0
                total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
                duration = (total / fps) if fps > 0 else 0
                w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH) or 0)
                h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT) or 0)
                cap.release()
                meta = {
                    "duration_sec": round(duration, 1),
                    "fps": round(fps, 1),
                    "resolution": f"{w}x{h}" if w > 0 else "unknown",
                    "total_frames": total,
                }
                _VIDEO_META_CACHE[cache_key] = meta

            videos.append({
                "filename": f.name,
                "path": rel_path,
                "folder": folder_rel,
                "size_mb": round(st.st_size / (1024 * 1024), 1),
                "duration_sec": meta["duration_sec"],
                "fps": meta["fps"],
                "resolution": meta["resolution"],
                "total_frames": meta["total_frames"],
            })
        except Exception:
            try:
                rel_path = f.relative_to(TEST_VIDEOS_DIR).as_posix()
                folder_rel = get_test_video_folder(f)
            except Exception:
                rel_path = f.name
                folder_rel = ""
            videos.append({
                "filename": f.name,
                "path": rel_path,
                "folder": folder_rel,
                "size_mb": round(f.stat().st_size / (1024 * 1024), 1),
            })

    # Also include any subdirectories inside TEST_VIDEOS_DIR
    for d in TEST_VIDEOS_DIR.rglob("*"):
        if d.is_dir():
            try:
                rel_d = d.relative_to(TEST_VIDEOS_DIR).as_posix()
                if rel_d and rel_d != ".":
                    folders_set.add(rel_d)
            except Exception:
                pass

    sorted_folders = sorted(list(folders_set))
    return jsonify({"ok": True, "videos": videos, "folders": sorted_folders})


@mode_bp.post("/api/test_videos/upload")
@role_required("tmc_officer")
def api_upload_test_video():
    """Upload a new .mp4 file to the test_videos/ directory or a specific subfolder."""
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

    # Optional target subfolder
    target_folder = (request.form.get("folder") or "").strip().replace("\\", "/").lstrip("/")
    if target_folder:
        parts = Path(target_folder).parts
        if any(p == ".." for p in parts):
            return jsonify({"ok": False, "error": "Invalid target folder"}), 400
        dest_dir = (TEST_VIDEOS_DIR / target_folder).resolve()
        try:
            if not dest_dir.is_relative_to(TEST_VIDEOS_DIR.resolve()):
                return jsonify({"ok": False, "error": "Access denied"}), 403
        except AttributeError:
            if not str(dest_dir).startswith(str(TEST_VIDEOS_DIR.resolve())):
                return jsonify({"ok": False, "error": "Access denied"}), 403
        dest_dir.mkdir(parents=True, exist_ok=True)
    else:
        dest_dir = TEST_VIDEOS_DIR

    dest = dest_dir / safe_name
    try:
        file.save(str(dest))
        size_mb = round(dest.stat().st_size / (1024 * 1024), 1)
        rel_path = dest.relative_to(TEST_VIDEOS_DIR).as_posix()
        folder_rel = get_test_video_folder(dest)
        print(f"[UPLOAD] Saved test video: {rel_path} ({size_mb} MB)")
        return jsonify({
            "ok": True,
            "filename": safe_name,
            "path": rel_path,
            "size_mb": size_mb,
            "folder": folder_rel,
        })
    except Exception as e:
        # Clean up partial file
        if dest.exists():
            dest.unlink()
        return jsonify({"ok": False, "error": str(e)}), 500
