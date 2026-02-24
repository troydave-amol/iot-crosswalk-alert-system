import requests
import socketio
import time
import json

sio = socketio.Client()

API_URL = "http://localhost:5000/api/roi"

# 1. POST
print("--- POST /api/roi ---")
payload = {"x1": 100, "y1": 100, "x2": 600, "y2": 400, "image_w": 1280, "image_h": 720}
r = requests.post(API_URL, json=payload)
print(r.status_code, r.text)

# 2. GET
print("--- GET /api/roi ---")
r = requests.get(API_URL)
print(r.status_code, r.text)

# 3. SocketIO Handle
@sio.on('status_update')
def on_message(data):
    print("--- STATUS UPDATE PAYLOAD ---")
    print(json.dumps(data, indent=2))
    # Disconnect after getting one
    sio.disconnect()

print("--- Connecting to SocketIO ---")
sio.connect('http://localhost:5000')
sio.wait()
