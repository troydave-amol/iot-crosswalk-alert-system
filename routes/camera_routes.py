"""
camera_routes.py — Camera stream, snapshot, status, and reconnect endpoints.

Blueprint: ``camera_bp``
Routes:
    GET  /video_feed           → MJPEG stream
    GET  /api/camera/snapshot  → single JPEG frame (no overlay)
    GET  /api/camera/status    → pipeline status JSON
    POST /api/camera/reconnect → force camera reconnect
"""

import time

import cv2
from flask import Blueprint, request, jsonify, Response

from auth.decorators import login_required
from config import STREAM_FPS, STREAM_SCALE
from services.session_manager import session_mgr

camera_bp = Blueprint("camera", __name__)


@camera_bp.route("/video_feed")
@login_required
def video_feed_route():
    """MJPEG stream from the active session (live camera or video test)."""
    overlay = request.args.get("overlay", "1") == "1"
    active = session_mgr.get_active()
    if active is None:
        return Response("No active session", status=503)

    return Response(
        gen_frames(active, overlay=overlay),
        mimetype="multipart/x-mixed-replace; boundary=frame",
    )


@camera_bp.get("/api/camera/snapshot")
@login_required
def api_camera_snapshot():
    """Return a single JPEG frame from the active session (full resolution, no overlay).
    Used by the ROI 'Capture Frame' button."""
    active = session_mgr.get_active()
    if active is None:
        return Response("No active session", status=503)

    frame = active.get_stream_frame(overlay=False)
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


def gen_frames(session_obj, overlay: bool = True):
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
        while not session_obj.stop_event.is_set():
            t0 = time.perf_counter()

            frame = session_obj.get_stream_frame(overlay=overlay)
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


@camera_bp.get("/api/camera/status")
@login_required
def api_camera_status():
    """Returns the current active session / AI pipeline status."""
    active = session_mgr.get_active()
    mode = session_mgr.get_mode()
    if active is None:
        return jsonify({
            "ok": True,
            "camera_online": False,
            "stream_connected": False,
            "ai_running": False,
            "ai_error": "No active session",
            "reconnect_attempts": 0,
            "last_frame_time": 0,
            "rtsp_url_masked": "",
            "mode": mode,
        })
    return jsonify({"ok": True, "mode": mode, **active.get_status()})


@camera_bp.post("/api/camera/reconnect")
@login_required
def api_camera_reconnect():
    """Force the active session to reconnect (only if actually broken)."""
    active = session_mgr.get_active()
    if active is None:
        return jsonify({"ok": False, "error": "No session"}), 503

    # If camera is already online and streaming, don't destroy the connection.
    if active.camera_online and active.stream_connected:
        print("[LIVE] Reconnect requested but session is already online — skipping")
        return jsonify({"ok": True, "action": "already_online"})

    # Session is genuinely offline/broken — force reconnect
    if active.cap is not None:
        try:
            active.cap.release()
        except Exception:
            pass
        active.cap = None
    active.camera_online = False
    active.stream_connected = False
    print("[LIVE] Manual reconnect requested — forcing capture reset")
    return jsonify({"ok": True, "action": "reconnecting"})
