"""
app.py — Flask Application Factory and entry point.

This is the thin top-level module that wires together all the extracted
components (config, extensions, routes, services, sockets) and starts the
Flask-SocketIO server.

Start the server::

    python app.py
"""

import os
from flask import Flask
from dotenv import load_dotenv

load_dotenv()


def create_app() -> Flask:
    """Flask application factory."""
    app = Flask(__name__)
    app.config["SECRET_KEY"] = os.getenv("SECRET_KEY", "dev-secret-key-change-in-production")

    # Import and bind SocketIO to this app instance
    from extensions import socketio
    socketio.init_app(app)

    # Register all route blueprints
    from routes import register_blueprints
    register_blueprints(app)

    # Register Socket.IO event handlers
    from sockets.handlers import register_socket_handlers
    register_socket_handlers()

    return app


# ────────────────────────────────────────────────────────────────────────────
# Entry Point
# ────────────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    from config import TEST_VIDEO_MAX_UPLOAD_MB
    from db import init_db
    from extensions import socketio
    from services.session_manager import session_mgr
    from services.camera_health import camera_health_monitor

    # Create the Flask app
    app = create_app()

    # Initialize DB (safe to run multiple times)
    init_db()

    # Set max upload size for video files
    app.config["MAX_CONTENT_LENGTH"] = TEST_VIDEO_MAX_UPLOAD_MB * 1024 * 1024

    # Auto-start Hikvision CCTV session on boot
    session_mgr.auto_start_live()

    # Start camera health monitor (independent TCP probe + stream watchdog)
    camera_health_monitor.start()

    # Run the Flask-SocketIO server
    socketio.run(app, host="0.0.0.0", port=5000, debug=True, allow_unsafe_werkzeug=True)
