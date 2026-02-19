import time
import random
from datetime import datetime, timezone
from threading import Thread

from flask import Flask, render_template, request, jsonify
from flask_socketio import SocketIO

# DB Imports
from db import init_db, insert_event, fetch_events

app = Flask(__name__)
app.config["SECRET_KEY"] = "dev-secret"
# cors_allowed_origins="*" allows the frontend to connect from different ports
# This is crucial for local dev where frontend might be served differently (though here it's same origin)
socketio = SocketIO(app, cors_allowed_origins="*")

# --------------------------------------------------------------------------------
# Global System State
# --------------------------------------------------------------------------------
# Holds the current state of the "virtual" edge device.
# Fields match the strict JSON Contract in static/js/contract.js
system_state = {
    # -- Detection & ROI --
    "child_in_roi": False,
    "roi_status": "OUTSIDE",
    "confidence": 0.0,
    "latency_ms": 45,
    
    # -- Warning Logic --
    "warning_logic_on": False,
    "switch_enabled": True,  # Default: Master Switch is ON
    "warning_device_on": False,
    
    # -- Power System --
    "battery_percent": 85.0,
    "solar_status": "Charging",  # "Charging" | "Not charging"
    
    # -- Optional / Context --
    "scenario": "Normal",
    "camera_status": "OK",
    "edge_status": "OK",
    "led_driver_status": "Ready"
}

# --------------------------------------------------------------------------------
# Helper Functions
# --------------------------------------------------------------------------------

def build_status_payload():
    """
    Constructs the payload dictionary strictly adhering to the Data Contract.
    Adds the required timestamp_iso and source metadata.
    Does NOT modify global state.
    """
    payload = system_state.copy()
    # Use UTC to align with DB storage best practices
    payload["timestamp_iso"] = datetime.now(timezone.utc).isoformat()
    payload["source"] = "backend" 
    return payload

def background_status_loop():
    """
    Simulates the Edge AI logic and Hardware IO.
    Runs in a background thread and emits 'status_update' every 1 second.
    """
    print("Background simulation loop started.")
    
    # Simulation counters
    tick = 0
    child_present_timer = 0
    
    # State tracking for logging
    last_logged = {
        "child_in_roi": None,
        "warning_device_on": None,
        "switch_enabled": None,
        "roi_status": None,
        "solar_status": None,
        "battery_percent": -1.0,
        "last_log_time": 0
    }

    while True:
        # --- 1. Simulate Inputs (Child Detection) ---
        # Logic: Randomly trigger a detection event every now and then
        if child_present_timer > 0:
            child_present_timer -= 1
            detected = True
        else:
            detected = False
            # 10% chance to start a detection event if not currently detecting
            # Occurs roughly every 10 seconds on average
            if random.random() < 0.1: 
                child_present_timer = random.randint(3, 8) # Duration: 3-8 seconds
                detected = True

        # --- 2. Update Detection State ---
        system_state["child_in_roi"] = detected
        system_state["roi_status"] = "INSIDE" if detected else "OUTSIDE"
        if detected:
             # High confidence when detected (0.75 - 0.99)
            system_state["confidence"] = round(random.uniform(0.75, 0.99), 2)
        else:
            # Low confidence noise when clear (0.0 - 0.1)
            system_state["confidence"] = round(random.uniform(0.0, 0.1), 2)
            
        system_state["latency_ms"] = random.randint(30, 80)

        # --- 3. Apply Strict Warning Logic (Contract Rules) ---
        
        # Rule 1: warning_logic_on MUST equal child_in_roi
        # simulation of the logic controller's output
        system_state["warning_logic_on"] = system_state["child_in_roi"]
        
        # Rule 2: warning_device_on === (warning_logic_on && switch_enabled)
        # simulation of the physical relay/MOSFET
        system_state["warning_device_on"] = system_state["warning_logic_on"] and system_state["switch_enabled"]

        # --- 4. Simulate Power System ---
        # Logic: Solar charges during "day", drains at "night" or when warning is ON
        # We'll simulate a day/night cycle every 40 ticks
        is_sunny = (tick % 40) < 20 
        
        if is_sunny:
            system_state["solar_status"] = "Charging"
            # Charge up
            system_state["battery_percent"] += 0.5
        else:
            system_state["solar_status"] = "Not charging"
            # Drain
            system_state["battery_percent"] -= 0.2

        # Extra drain if warning light is ON
        if system_state["warning_device_on"]:
            system_state["battery_percent"] -= 0.1

        # Clamp battery 0-100
        system_state["battery_percent"] = max(0.0, min(100.0, round(system_state["battery_percent"], 1)))

        # --- 5. Emit Status Update ---
        payload = build_status_payload()
        
        # broadcast=True is default for emit() but explicit is better
        socketio.emit("status_update", payload)

        # --- 6. Persistent Logging Logic ---
        try:
            should_log = False
            current_time = time.time()
            
            # Check meaningful changes
            if (payload["child_in_roi"] != last_logged["child_in_roi"] or
                payload["warning_device_on"] != last_logged["warning_device_on"] or
                payload["switch_enabled"] != last_logged["switch_enabled"] or
                payload["roi_status"] != last_logged["roi_status"] or
                payload["solar_status"] != last_logged["solar_status"]):
                should_log = True
                
            # Check significant battery change (>= 1.0%)
            if abs(payload["battery_percent"] - last_logged["battery_percent"]) >= 1.0:
                should_log = True

            # Heartbeat force log every 60 seconds
            if current_time - last_logged["last_log_time"] > 60:
                should_log = True

            if should_log:
                insert_event(payload)
                
                # Update last logged state
                last_logged["child_in_roi"] = payload["child_in_roi"]
                last_logged["warning_device_on"] = payload["warning_device_on"]
                last_logged["switch_enabled"] = payload["switch_enabled"]
                last_logged["roi_status"] = payload["roi_status"]
                last_logged["solar_status"] = payload["solar_status"]
                last_logged["battery_percent"] = payload["battery_percent"]
                last_logged["last_log_time"] = current_time

        except Exception as e:
            # Catch-all to ensure logging logic never crashes the status loop
            print(f"Logging Logic Error: {e}")

        
        # Loop delay
        tick += 1
        time.sleep(1)

# --------------------------------------------------------------------------------
# Routes & Events
# --------------------------------------------------------------------------------

@app.route("/")
def index():
    return render_template("index.html")

@socketio.on("connect")
def handle_connect():
    """
    Triggered when a client connects (dashboard loads or refreshes).
    Sends the immediate state so the dashboard populates instantly.
    """
    print("Client connected")
    payload = build_status_payload()
    socketio.emit("status_update", payload)

    socketio.emit("status_update", payload)

# --------------------------------------------------------------------------------
# API Routes
# --------------------------------------------------------------------------------

@app.route("/api/health")
def api_health():
    """
    Simple health check.
    Returns 200 OK if server is running.
    """
    return jsonify({"ok": True})

@app.route("/api/events")
def api_events_route():
    """
    Get historical events from DB.
    Returns 503 if DB is unavailable.
    """
    try:
        # Parse Query Params
        range_arg = request.args.get("range", "all")
        limit = int(request.args.get("limit", 50))
        offset = int(request.args.get("offset", 0))
        
        # Boolean flags usually come as strings "true"/"false" or just present
        # Here we assume "true" string for True, anything else False for safety
        warning_only = request.args.get("warning_only", "false").lower() in ("true", "1")
        in_roi_only = request.args.get("in_roi_only", "false").lower() in ("true", "1")
        
        min_conf = float(request.args.get("min_conf", 0.0))
        scenario = request.args.get("scenario", None)
        search = request.args.get("search", None)

        # Enforce max limit
        if limit > 500:
            limit = 500

        data = fetch_events(
            limit=limit,
            offset=offset,
            time_range=range_arg,
            warning_only=warning_only,
            in_roi_only=in_roi_only,
            min_conf=min_conf,
            scenario=scenario,
            search=search
        )
        
        response = {
            "ok": True,
            "total": data["total"],
            "rows": data["rows"]
        }
        return jsonify(response)

    except Exception as e:
        print(f"API EVENTS ERROR: {e}")
        # Return 503 Service Unavailable if DB fails
        return jsonify({"ok": False, "error": "db_unavailable"}), 503

# --------------------------------------------------------------------------------
# Entry Point
# --------------------------------------------------------------------------------
if __name__ == "__main__":
    # Initialize DB (safe to run multiple times)
    init_db()

    # Start the background simulation thread
    t = Thread(target=background_status_loop, daemon=True)
    t.start()
    
    # Run the Flask-SocketIO server
    socketio.run(app, host="0.0.0.0", port=5000, debug=True)
