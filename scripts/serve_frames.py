"""
serve_frames.py
Simple HTTP server to serve frame images for Label Studio.
Run on port 8091 while Label Studio runs on port 8090.
"""

import http.server
import socketserver
import os
import sys

PORT = 8095
DIRECTORY = r"C:\Users\Acer\Documents\CAPSTONE\web_dashboard_analytics\datasets\afternoon_v1\frames_selected"

class CORSRequestHandler(http.server.SimpleHTTPRequestHandler):
    """HTTP handler with CORS headers so Label Studio can load images."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=DIRECTORY, **kwargs)

    def end_headers(self):
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "*")
        super().end_headers()

    def do_OPTIONS(self):
        self.send_response(200)
        self.end_headers()

print(f"Serving frames from: {DIRECTORY}")
print(f"URL: http://localhost:{PORT}/")
print(f"Example: http://localhost:{PORT}/aft_245_315_01_00000.jpg")
print("Press Ctrl+C to stop.\n")

with socketserver.TCPServer(("", PORT), CORSRequestHandler) as httpd:
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nServer stopped.")
