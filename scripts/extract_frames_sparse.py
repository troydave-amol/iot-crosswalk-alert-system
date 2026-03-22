"""
extract_frames_sparse.py
Extracts 1 frame every N seconds from all videos in videos_raw/.
Outputs JPEG frames into frames_5s/ preserving subfolder structure.
"""

import cv2
from pathlib import Path

# ── Configuration ──────────────────────────────────────────────
PROJECT_ROOT = Path(r"C:\Users\Acer\Documents\CAPSTONE\web_dashboard_analytics")
VIDEO_ROOT = PROJECT_ROOT / "datasets" / "afternoon" / "videos_raw"
OUTPUT_ROOT = PROJECT_ROOT / "datasets" / "afternoon" / "frames_5s"
INTERVAL_SECONDS = 5
# ───────────────────────────────────────────────────────────────

OUTPUT_ROOT.mkdir(parents=True, exist_ok=True)

video_files = (
    list(VIDEO_ROOT.rglob("*.mp4"))
    + list(VIDEO_ROOT.rglob("*.avi"))
    + list(VIDEO_ROOT.rglob("*.mkv"))
)

if not video_files:
    print(f"No video files found in {VIDEO_ROOT}")
    exit(1)

print(f"Found {len(video_files)} video(s) in {VIDEO_ROOT}\n")

total_saved = 0

for video_path in sorted(video_files):
    cap = cv2.VideoCapture(str(video_path))
    if not cap.isOpened():
        print(f"  FAILED to open: {video_path}")
        continue

    fps = cap.get(cv2.CAP_PROP_FPS)
    total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))

    if fps <= 0:
        print(f"  Invalid FPS for: {video_path}")
        cap.release()
        continue

    frame_interval = int(fps * INTERVAL_SECONDS)
    video_name = video_path.stem
    rel_parent = video_path.parent.name

    duration_sec = total_frames / fps
    expected_frames = int(duration_sec / INTERVAL_SECONDS)

    print(f"Processing: {rel_parent}/{video_name}")
    print(f"  FPS={fps:.1f}  Duration={duration_sec:.0f}s  Expected~{expected_frames} frames")

    out_dir = OUTPUT_ROOT / rel_parent / video_name
    out_dir.mkdir(parents=True, exist_ok=True)

    count = 0
    saved = 0

    while True:
        ret, frame = cap.read()
        if not ret:
            break

        if count % frame_interval == 0:
            out_name = f"{video_name}_{saved:05d}.jpg"
            cv2.imwrite(str(out_dir / out_name), frame)
            saved += 1

        count += 1

    cap.release()
    total_saved += saved
    print(f"  Saved {saved} frames -> {out_dir}\n")

print(f"{'='*50}")
print(f"TOTAL FRAMES EXTRACTED: {total_saved}")
print(f"Output directory: {OUTPUT_ROOT}")
