import cv2
import os
from pathlib import Path

# ── Configuration ──────────────────────────────────────────────
PROJECT_ROOT = Path(r"C:\Users\Acer\Documents\CAPSTONE\web_dashboard_analytics")
# Input directly from the user's gathering folder
VIDEO_ROOT = Path(r"C:\Users\Acer\Documents\CAPSTONE\CAMERA\VIDEOS\Afternoon_V2")
# Output to the project's dataset folder mirroring morning_v1 structure
OUTPUT_ROOT = PROJECT_ROOT / "datasets" / "source_afternoon_v2" / "raw_frames"
INTERVAL_SECONDS = 3  # 1 frame every 3 seconds
# ───────────────────────────────────────────────────────────────

def extract_frames():
    OUTPUT_ROOT.mkdir(parents=True, exist_ok=True)
    
    # Supported video formats
    video_files = (
        list(VIDEO_ROOT.rglob("*.mp4"))
        + list(VIDEO_ROOT.rglob("*.avi"))
        + list(VIDEO_ROOT.rglob("*.mkv"))
        + list(VIDEO_ROOT.rglob("*.mov"))
    )
    
    if not video_files:
        print(f"No video files found in {VIDEO_ROOT}")
        return
        
    print(f"Found {len(video_files)} video(s) in {VIDEO_ROOT}")
    print(f"Extracting 1 frame every {INTERVAL_SECONDS} seconds.\n")
    
    total_saved = 0
    
    for video_path in sorted(video_files):
        print(f"Opening: {video_path.name}")
        cap = cv2.VideoCapture(str(video_path))
        
        if not cap.isOpened():
            print(f"  [ERROR] FAILED to open: {video_path}")
            continue
            
        fps = cap.get(cv2.CAP_PROP_FPS)
        total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        
        if fps <= 0:
            print(f"  [WARNING] Invalid FPS for: {video_path}. Skipping.")
            cap.release()
            continue
            
        frame_interval = int(fps * INTERVAL_SECONDS)
        video_name = video_path.stem
        
        # Calculate expected metrics
        duration_sec = total_frames / fps
        expected_frames = int(duration_sec / INTERVAL_SECONDS)
        
        print(f"  FPS: {fps:.1f} | Duration: {duration_sec:.0f}s | Expected Frames: ~{expected_frames}")
        
        # We save directly into a subfolder for this specific video
        out_dir = OUTPUT_ROOT / video_name
        out_dir.mkdir(parents=True, exist_ok=True)
        
        count = 0
        saved = 0
        
        while True:
            ret, frame = cap.read()
            if not ret:
                break
                
            if count % frame_interval == 0:
                # Use a specific prefix to distinguish from V1 afternoon
                out_name = f"AftV2_{video_name}_{saved:05d}.jpg"
                out_path = out_dir / out_name
                cv2.imwrite(str(out_path), frame)
                saved += 1
                
            count += 1
            
        cap.release()
        total_saved += saved
        print(f"  -> Saved {saved} frames to {out_dir}\n")
        
    print(f"{'='*50}")
    print(f"TOTAL FRAMES EXTRACTED: {total_saved}")
    print(f"Output directory: {OUTPUT_ROOT}")
    print(f"Next step: Manually review these frames and copy the best into datasets/source_afternoon_v2/raw_frames!")

if __name__ == "__main__":
    extract_frames()
