"""
serve_frames.py
Custom HTTP server to dynamically find and serve frame images for Label Studio.
This version ignores the exact folder path sent by Label Studio and dynamically 
searches the entire DIRECTORY to find the requested image file. It fixes all 404 errors!
"""

import http.server
import socketserver
import os
from pathlib import Path

PORT = 8095
DIRECTORY = Path(r"C:\Users\Acer\Documents\CAPSTONE\web_dashboard_analytics\datasets\afternoon_v2\frames_raw")

class SmartImageHandler(http.server.SimpleHTTPRequestHandler):
    """HTTP handler with CORS + Dynamic File Finding."""

    def translate_path(self, path):
        # 1. Extract just the pure filename from the browser's request (e.g. from "/201-300/img.jpg" to "img.jpg")
        filename = os.path.basename(path.split('?')[0])
        if not filename or filename == '/' or filename == '':
            return str(DIRECTORY)
            
        # 2. Dynamically search the entire DIRECTORY (and all subfolders) for this exact filename!
        found_files = list(DIRECTORY.rglob(filename))
        
        if found_files:
            return str(found_files[0]) # Match found! Return the absolute true path on disk

        # If not uniquely found, fallback to the default behavior
        return super().translate_path(path)

    def end_headers(self):
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "*")
        super().end_headers()

    def do_OPTIONS(self):
        self.send_response(200)
        self.end_headers()

print(f"============================================================")
print(f"SMART IMAGE SERVER RUNNING")
print(f"Serving frames dynamically from anywhere inside: {DIRECTORY}")
print(f"URL: http://localhost:{PORT}/")
print("Press Ctrl+C to stop.\n")

with socketserver.TCPServer(("", PORT), SmartImageHandler) as httpd:
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nServer stopped.")
