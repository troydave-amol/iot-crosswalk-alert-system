import cv2
import os
from pathlib import Path

# ── Configuration ──────────────────────────────────────────────
PROJECT_ROOT = Path(r"C:\Users\Acer\Documents\CAPSTONE\web_dashboard_analytics")
VIDEO_PATH = Path(r"C:\Users\Acer\Documents\CAPSTONE\CAMERA\VIDEOS\Morning_V1\192.168.1.64_01_20260325062548946_5.mp4")
OUTPUT_ROOT = PROJECT_ROOT / "datasets" / "source_morning_v1" / "raw_frames" / "morning_v1_clip_20260325062548946_segment_5_dense"

# Segments in seconds (start_time, end_time)
SEGMENTS = [
    (int(4*60 + 30), int(4*60 + 41)),  # 4:30 to 4:41
]

INTERVAL_SECONDS = 1.0  # 1 frame per second
# ───────────────────────────────────────────────────────────────

def extract_dense_frames():
    OUTPUT_ROOT.mkdir(parents=True, exist_ok=True)
    
    video_path = VIDEO_PATH
    if not video_path.exists():
        print(f"[ERROR] Video not found: {video_path}")
        # Search for .avi or .mkv just in case
        valid = False
        for ext in ['.avi', '.mkv', '.mov']:
            alt_path = video_path.with_suffix(ext)
            if alt_path.exists():
                print(f"Found {alt_path.name} instead, using that.")
                video_path = alt_path
                valid = True
                break
        if not valid:
            return

    print(f"Opening video: {video_path.name}")
    cap = cv2.VideoCapture(str(video_path))

    if not cap.isOpened():
        print("[ERROR] Failed to open video file")
        return

    fps = cap.get(cv2.CAP_PROP_FPS)
    if fps <= 0:
        print("[ERROR] Invalid FPS. Can't process.")
        cap.release()
        return
        
    for start_sec, end_sec in SEGMENTS:
        print(f"\nProcessing segment: {start_sec}s to {end_sec}s (Duration: {end_sec - start_sec}s)")
        
        # Set frame pointer to start_sec
        start_frame = int(start_sec * fps)
        cap.set(cv2.CAP_PROP_POS_FRAMES, start_frame)
        
        current_sec = start_sec
        frames_saved = 0
        
        while current_sec <= end_sec:
            ret, frame = cap.read()
            if not ret:
                print("  Reached end of video unexpectedly")
                break
                
            # Write exactly at the 1-second interval marks
            filename = f"{video_path.stem}_dense_{current_sec:.1f}s.jpg"
            out_path = OUTPUT_ROOT / filename
            cv2.imwrite(str(out_path), frame)
            frames_saved += 1
            
            # Jump forward by 1 second (minus the 1 frame we just read)
            current_sec += INTERVAL_SECONDS
            next_frame = int(current_sec * fps)
            cap.set(cv2.CAP_PROP_POS_FRAMES, next_frame)
            
        print(f"  -> Saved {frames_saved} frames for this segment.")

    cap.release()
    print(f"\nDone! Dense frames saved to: {OUTPUT_ROOT}")

if __name__ == "__main__":
    extract_dense_frames()
