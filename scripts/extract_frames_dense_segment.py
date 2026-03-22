"""
extract_frames_dense_segment.py
Extract dense frames (1 frame every 2 seconds) from a specific time segment
of a single video file.
"""

import cv2
from pathlib import Path

# ── Configuration ──────────────────────────────────────────────
PROJECT_ROOT = Path(r"C:\Users\Acer\Documents\CAPSTONE\web_dashboard_analytics")
VIDEO_PATH = PROJECT_ROOT / "datasets" / "afternoon" / "videos_raw" / "aft_400_445" / "aft_400_445_03.mp4"
OUTPUT_ROOT = PROJECT_ROOT / "datasets" / "afternoon" / "frames_dense"

# Time segment (minutes:seconds)
START_TIME = (0, 0)   # 00:00
END_TIME   = (0, 8)   # 00:08

INTERVAL_SECONDS = 1  # 1 frame every 1 second
# ───────────────────────────────────────────────────────────────

start_sec = START_TIME[0] * 60 + START_TIME[1]
end_sec   = END_TIME[0] * 60 + END_TIME[1]

video_name = VIDEO_PATH.stem
out_dir = OUTPUT_ROOT / video_name / f"{start_sec}s_{end_sec}s"
out_dir.mkdir(parents=True, exist_ok=True)

cap = cv2.VideoCapture(str(VIDEO_PATH))
if not cap.isOpened():
    print(f"Failed to open: {VIDEO_PATH}")
    exit(1)

fps = cap.get(cv2.CAP_PROP_FPS)
total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
duration = total_frames / fps

print(f"Video: {VIDEO_PATH.name}")
print(f"FPS: {fps:.1f}  Duration: {duration:.0f}s")
print(f"Segment: {START_TIME[0]}:{START_TIME[1]:02d} – {END_TIME[0]}:{END_TIME[1]:02d}  ({end_sec - start_sec}s)")
print(f"Interval: 1 frame every {INTERVAL_SECONDS}s")
print(f"Output: {out_dir}\n")

start_frame = int(start_sec * fps)
end_frame = int(end_sec * fps)
frame_interval = int(fps * INTERVAL_SECONDS)

cap.set(cv2.CAP_PROP_POS_FRAMES, start_frame)

saved = 0
current = start_frame

while current <= end_frame:
    cap.set(cv2.CAP_PROP_POS_FRAMES, current)
    ret, frame = cap.read()
    if not ret:
        break

    timestamp = current / fps
    out_name = f"{video_name}_dense_{timestamp:.1f}s.jpg"
    cv2.imwrite(str(out_dir / out_name), frame)
    saved += 1
    current += frame_interval

cap.release()
print(f"Done — saved {saved} dense frames to {out_dir}")
