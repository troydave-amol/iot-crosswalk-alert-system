"""
handlers.py — Socket.IO event handlers (connect, disconnect, request_status).

Registers WebSocket event handlers with the ``socketio`` instance from
``extensions.py``.  Call ``register_socket_handlers()`` once during app
factory initialization.
"""

from flask import session
from flask_socketio import join_room

from extensions import socketio
from services.live_session import build_idle_payload
from services.session_manager import session_mgr


def register_socket_handlers():
    """Register all Socket.IO event handlers."""

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

        active = session_mgr.get_active()
        mode = session_mgr.get_mode()

        if active is not None:
            cam_status = "OK" if active.camera_online else "OFFLINE"
            socketio.emit("status_update", build_idle_payload(camera_status=cam_status), room=_req.sid)
            socketio.emit("camera_status", active.get_status(), room=_req.sid)
            socketio.emit("mode_update", {
                "mode": mode,
                "video_filename": getattr(active, '_video_filename', None)
            }, room=_req.sid)
        else:
            socketio.emit("status_update", build_idle_payload(camera_status="OFFLINE"), room=_req.sid)
            socketio.emit("mode_update", {"mode": mode}, room=_req.sid)
