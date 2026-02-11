import time
from threading import Thread

from flask import Flask, render_template
from flask_socketio import SocketIO

app = Flask(__name__)
app.config["SECRET_KEY"] = "dev-secret"
socketio = SocketIO(app, cors_allowed_origins="*")  # local dev OK

# Fake live status for testing
system_state = {
    "child_in_roi": False,
    "warning_on": False,
    "confidence": 0.0
}

def background_status_loop():
    toggle = False
    while True:
        toggle = not toggle
        system_state["child_in_roi"] = toggle
        system_state["warning_on"] = toggle
        system_state["confidence"] = 0.78 if toggle else 0.12

        socketio.emit("status_update", system_state)
        time.sleep(1)

@app.route("/")
def index():
    return render_template("index.html")

@socketio.on("connect")
def handle_connect():
    # Send current status immediately when dashboard connects
    socketio.emit("status_update", system_state)

if __name__ == "__main__":
    t = Thread(target=background_status_loop, daemon=True)
    t.start()

    socketio.run(app, host="0.0.0.0", port=5000, debug=True)
