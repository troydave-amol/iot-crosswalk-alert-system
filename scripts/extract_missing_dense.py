import cv2
import os
from pathlib import Path

PROJECT_ROOT = Path(r"C:\Users\Acer\Documents\CAPSTONE\web_dashboard_analytics")
# The video Label Studio is currently looking for!
VIDEO_PATH = Path(r"C:\Users\Acer\Documents\CAPSTONE\CAMERA\VIDEOS\Afternoon_V2\192.168.1.64_01_20260325124805618.mp4")
OUTPUT_ROOT = PROJECT_ROOT / "datasets" / "afternoon_v2" / "frames_raw" / "301-319"

SEGMENTS = [(0, 19)]  # 0 to 19 seconds
INTERVAL_SECONDS = 0.5

def extract_dense_frames():
    OUTPUT_ROOT.mkdir(parents=True, exist_ok=True)
    
    video_path = VIDEO_PATH
    # Allow alternative extensions
    if not video_path.exists():
        for ext in ['.avi', '.mkv', '.mov']:
            alt_path = video_path.with_suffix(ext)
            if alt_path.exists():
                video_path = alt_path
                break

    print(f"Opening video: {video_path.name}")
    cap = cv2.VideoCapture(str(video_path))

    if not cap.isOpened():
        print("[ERROR] Failed to open video file")
        return

    fps = cap.get(cv2.CAP_PROP_FPS)

    for start_sec, end_sec in SEGMENTS:
        current_time_s = start_sec
        frames_saved = 0
        
        while current_time_s <= end_sec:
            frame_idx = int(current_time_s * fps)
            cap.set(cv2.CAP_PROP_POS_FRAMES, frame_idx)
            
            ret, frame = cap.read()
            if not ret: break
                
            # Exactly match the missing file name Label Studio is asking for!
            filename = f"AftV2_dense_{video_path.stem}_{current_time_s:04.1f}s.jpg"
            out_path = OUTPUT_ROOT / filename
            cv2.imwrite(str(out_path), frame)
            frames_saved += 1
            
            current_time_s += INTERVAL_SECONDS

    cap.release()
    print(f"Done! Saved {frames_saved} frames directly to {OUTPUT_ROOT}")

if __name__ == "__main__":
    extract_dense_frames()
