"""
extensions.py — Neutral shared extension instances.

Instantiates Flask-SocketIO (and any future extensions) WITHOUT importing
app-specific modules.  Every module that needs ``socketio`` imports it from
here, breaking circular-dependency chains by design.

Usage
-----
    from extensions import socketio

In the application factory (``app.py``), call::

    socketio.init_app(app)
"""

from flask_socketio import SocketIO

# Created *without* an app; ``init_app`` is called later in the factory.
socketio = SocketIO(cors_allowed_origins="*", async_mode="threading")
