import cv2
import os
from pathlib import Path

# ── Configuration ──────────────────────────────────────────────
PROJECT_ROOT = Path(r"C:\Users\Acer\Documents\CAPSTONE\web_dashboard_analytics")
VIDEO_PATH = Path(r"C:\Users\Acer\Documents\CAPSTONE\CAMERA\VIDEOS\Afternoon_V2\192.168.1.64_01_20260325125128711.mp4")
OUTPUT_ROOT = PROJECT_ROOT / "datasets" / "source_afternoon_v2" / "raw_frames" / "afternoon_v2_clip_20260325125128711_dense"

# Segments in seconds (start_time, end_time)
SEGMENTS = [
    (0, 19),  # 0:00 to 0:19
]

INTERVAL_SECONDS = 0.5  # 1 frame every 0.5 seconds (2 FPS)
# ───────────────────────────────────────────────────────────────

def extract_dense_frames():
    OUTPUT_ROOT.mkdir(parents=True, exist_ok=True)
    
    video_path = VIDEO_PATH
    if not video_path.exists():
        # Check alternative formats
        valid = False
        for ext in ['.avi', '.mkv', '.mov']:
            alt_path = video_path.with_suffix(ext)
            if alt_path.exists():
                print(f"Found {alt_path.name} instead, using that.")
                video_path = alt_path
                valid = True
                break
        if not valid:
            print(f"[ERROR] Video not found: {video_path}")
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
    
    print(f"FPS: {fps}")
        
    for start_sec, end_sec in SEGMENTS:
        print(f"\nProcessing segment: {start_sec}s to {end_sec}s (Duration: {end_sec - start_sec}s)")
        
        current_time_s = start_sec
        frames_saved = 0
        
        while current_time_s <= end_sec:
            # Set the exact frame at current_time_s
            frame_idx = int(current_time_s * fps)
            cap.set(cv2.CAP_PROP_POS_FRAMES, frame_idx)
            
            ret, frame = cap.read()
            if not ret:
                print("  Reached end of video unexpectedly")
                break
                
            # Filename for easy sorting in Label Studio
            filename = f"AftV2_{video_path.stem}_dense_{current_time_s:05.1f}s.jpg"
            out_path = OUTPUT_ROOT / filename
            cv2.imwrite(str(out_path), frame)
            frames_saved += 1
            
            current_time_s += INTERVAL_SECONDS
            
        print(f"  -> Saved {frames_saved} frames for this segment.")

    cap.release()
    print(f"\nDone! Dense frames saved to: {OUTPUT_ROOT}")

if __name__ == "__main__":
    extract_dense_frames()
